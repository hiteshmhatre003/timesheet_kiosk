# -*- coding: utf-8 -*-
"""
Timesheet Kiosk API (v4)
-------------------------
Python port of the current Express routes (auth, employees, wih, timesheets).

v4 adapts to a schema change on Timesheet Allocation: it used to be one
record per USER (with a child table of WIH numbers). It is now one record
per WIH (a single Link field, `wih`), with a Table MultiSelect `user` field
letting several users share that WIH. In other words, a WIH's Employee
Timesheet is now a document SHARED by everyone allocated to it, not a
document each user gets their own private copy of.

That has knock-on effects handled throughout this file:
  - `_check_access` replaces the old strict `doc.user == session.user`
    check with "is this user currently allocated to this WIH, did they
    create this doc, or have they punched an entry on it".
  - `start_timer` / `stop_timer` only care about the CURRENT user's own
    running entry, since several teammates can each have an independent
    timer running on the same shared document at once.
  - `_build_timesheet_response` now filters `timesheet_entry` down to only
    the viewing user's own rows, and adds `personal_hours` (this user's own
    total) alongside `total_hours` (the whole team's combined total, still
    computed the same way it always was).
  - `list_wih` / `create_timesheet` treat "does an open timesheet already
    exist for this WIH" as a WIH-wide question, not a per-user one — if a
    teammate already started it, joining that one is correct, not creating
    a second, competing document.

v3 (kept for context) fixed a schema drift from v2: the live `Timesheet
Entry` doctype uses a field called `minutes` (Float) and an explicit
`is_running` (Check) field — NOT `duration_minutes`, which v2 wrote to.

Every function here is called from the frontend as:
    POST /api/method/timesheet_kiosk.api.<function_name>
with a JSON body containing the function's arguments.
"""

import frappe
from frappe.auth import LoginManager
from frappe.utils import today, now_datetime, time_diff_in_hours, flt

TS_DOCTYPE = "Employee Timesheet"
ALLOCATION_DOCTYPE = "Timesheet Allocation"
PAGE_SIZE = 10

# Only a user with this role may submit (lock) a shared timesheet. Everyone
# else allocated to the WIH can still log/edit/save their own time entries
# as before — this only gates the final submit_timesheet() step.
TIMESHEET_MANAGER_ROLE = "Timesheet Manager"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_user():
    if frappe.session.user == "Guest":
        frappe.throw("Not authenticated. Please log in.", frappe.AuthenticationError)
    return frappe.session.user


def _allocated_wih_numbers(user):
    """WIH numbers currently allocated to `user` via Timesheet Allocation.

    A single Timesheet Allocation record now represents ONE WIH shared by
    MULTIPLE users, selected through a Table MultiSelect `user` field. That
    field is backed by a child doctype (e.g. "User Multiselect") whose own
    fieldname for the actual User link is admin-defined, not something this
    code should hardcode a guess for. So it's resolved from the DocType
    metadata at runtime instead — this also means it keeps working even if
    the child doctype gets renamed or rebuilt later.
    """
    meta = frappe.get_meta(ALLOCATION_DOCTYPE)
    user_field = meta.get_field("user")
    if not user_field or not user_field.options:
        frappe.throw(
            f"{ALLOCATION_DOCTYPE}.user is not configured as expected "
            "(expected a Table MultiSelect field with a child doctype)."
        )
    child_doctype = user_field.options

    child_meta = frappe.get_meta(child_doctype)
    link_fieldname = next(
        (f.fieldname for f in child_meta.fields if f.fieldtype in ("Link", "Dynamic Link")),
        None,
    )
    if not link_fieldname:
        frappe.throw(f"Could not find a Link field on {child_doctype} to match the user against.")

    allocation_names = frappe.get_all(
        child_doctype,
        filters={
            "parenttype": ALLOCATION_DOCTYPE,
            "parentfield": "user",
            link_fieldname: user,
        },
        pluck="parent",
        limit_page_length=500,
    )
    if not allocation_names:
        return []

    wih_numbers = frappe.get_all(
        ALLOCATION_DOCTYPE,
        filters={"name": ["in", allocation_names]},
        pluck="wih",
        limit_page_length=500,
    )
    return [w for w in wih_numbers if w]


def _is_mine(entry, user):
    """True if `entry` (a Timesheet Entry row) belongs to `user` — or has no
    owner recorded at all. Rows punched before the `user` field existed (or
    while it wasn't actually saving — see _entry_user_field_exists below)
    have a blank `user`, and are treated as everyone's/no-one's rather than
    permanently un-ownable. Used everywhere an entry needs to be matched
    against "the current user's own row": start_timer's duplicate check,
    stop_timer's active-entry lookup, update_entry/delete_entry's
    ownership check, and _build_timesheet_response's per-viewer filtering.
    """
    owner = entry.get("user")
    return not owner or owner == user


def _entry_user_field_exists():
    """Whether Timesheet Entry currently has a `user` field at all, per the
    live DocType metadata. get_timesheet_stats queries `te.user` directly
    in raw SQL (unlike the doc-object `.get("user")` calls used elsewhere,
    which just return None for a missing field rather than erroring) — a
    genuinely missing column there is a hard SQL error, not a silent drop,
    and would otherwise crash the whole dashboard stats card.

    Deliberately NOT cached in a module-level variable here: frappe.get_meta()
    already caches DocType metadata and correctly invalidates that cache the
    moment the doctype is edited from the Desk UI. A second cache on top of
    that would keep answering "no" even after the field gets added, until
    the next worker restart — worse than just calling the (already cheap,
    already cached) framework function directly each time.
    """
    return bool(frappe.get_meta("Timesheet Entry").has_field("user"))



def _check_access(doc, user=None):
    """Replaces the old single-owner `_check_owner` check. Access to a
    (now potentially shared) Employee Timesheet is granted if the user:
      - created it, OR
      - is currently allocated to its WIH via Timesheet Allocation, OR
      - has previously punched at least one entry on it themselves
        (kept so nobody loses access to a document they worked on just
        because an admin later changes/removes the WIH allocation).
    """
    user = user or frappe.session.user
    if doc.user == user:
        return
    if doc.get("wih_number") and doc.wih_number in _allocated_wih_numbers(user):
        return
    # Deliberately strict (not _is_mine's lenient blank-owner match) — this
    # is a security-relevant fallback grant, so it should require genuine
    # proof this user personally punched something here, not just "some
    # row happens to have no owner recorded."
    if any(e.get("user") == user for e in (doc.get("timesheet_entry") or [])):
        return
    frappe.throw("You are not permitted to access this timesheet.", frappe.PermissionError)


def _is_timesheet_manager(user=None):
    user = user or frappe.session.user
    return TIMESHEET_MANAGER_ROLE in frappe.get_roles(user)


def _running_timer_users(doc):
    """Users (as {"user", "full_name"}) with a currently running entry
    ANYWHERE on this shared timesheet — the whole team, not just the
    viewer's own rows (unlike _build_timesheet_response's entry_list,
    which is deliberately filtered per-viewer). Only meant to be shown to
    a Timesheet Manager deciding whether they can submit yet; the role
    gate on who actually SEES this lives in _build_timesheet_response,
    not here.

    Legacy rows with no `user` recorded (see _is_mine's docstring) are
    skipped here — there's no name to show for them — but submit_timesheet
    still blocks on them separately via its own raw is_running check, so a
    running legacy row can't silently slip through submission just
    because it can't be attributed to anyone.
    """
    running_users = list(dict.fromkeys(
        e.get("user") for e in (doc.get("timesheet_entry") or [])
        if e.get("is_running") and e.get("user")
    ))
    if not running_users:
        return []
    users = frappe.get_all(
        "User", filters={"name": ["in", running_users]}, fields=["name", "full_name"]
    )
    name_map = {u.name: (u.full_name or u.name) for u in users}
    return [{"user": u, "full_name": name_map.get(u, u)} for u in running_users]


def _recalc_total_hours(doc):
    doc.total_hours = round(sum(flt(e.duration_hours) for e in doc.timesheet_entry), 2)


def _status_label(docstatus):
    """Single source of truth for the human-readable status shown on the
    app. Employee Timesheet also carries its own `status` Select field,
    but that field is only ever written by THIS app's own create_timesheet
    ("Draft") and submit_timesheet ("Submitted") — it has no way to know
    when a document is submitted or cancelled directly from the ERPNext
    desk UI, which only sets docstatus. Deriving the label from docstatus
    (0/1/2 — Frappe's own field, always correct no matter which path a
    submit/cancel came through) instead of trusting the stored field is
    what makes the app's displayed status always match reality.
    """
    return {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(docstatus, "Draft")


def _build_timesheet_response(doc, user=None):
    user = user or frappe.session.user
    entries = doc.get("timesheet_entry") or []

    # Only the viewing user's OWN punched entries are returned — the WIH's
    # timesheet is shared across everyone allocated to it, and each person
    # should see (and edit/delete) only the rows they personally punched,
    # not their teammates'. Legacy rows punched before the `user` field
    # existed have no owner recorded, so they're shown to everyone rather
    # than hidden from everyone (fails open, not closed).
    my_entries = [e for e in entries if _is_mine(e, user)]

    # is_running is the source of truth; fall back to the old heuristic
    # (start_time set, end_time blank) in case of pre-fix legacy rows.
    # Scoped to my_entries so the live-ticking timer on screen always
    # reflects THIS user's own running punch, never a teammate's.
    active_entry = next(
        (e for e in my_entries if e.get("is_running") or (e.start_time and not e.end_time)),
        None,
    )
    active_timer_started_at = None
    if active_entry:
        active_timer_started_at = str(active_entry.start_time).replace(" ", "T")

    # Elapsed hours for the user's own running entry, computed exactly the
    # way stop_timer() computes a finished entry's duration —
    # time_diff_in_hours(now_datetime(), start_time), both naive datetimes
    # in the site's own configured timezone. The frontend's live ticker
    # must add THIS to personal_hours, not re-derive elapsed time itself
    # from active_timer_started_at: that string carries no timezone
    # marker, so a browser whose local zone differs from the site's
    # System Settings timezone parses it as if it WERE in the browser's
    # own zone, silently shifting "elapsed" by the difference between the
    # two zones. That mismatch is what made "My Hours" show a wildly
    # inflated figure (hours, not minutes) for the whole time a timer ran.
    active_timer_elapsed_hours = None
    if active_entry:
        active_timer_elapsed_hours = round(
            time_diff_in_hours(now_datetime(), active_entry.start_time), 4
        )

    entry_list = []
    for e in sorted(my_entries, key=lambda row: row.idx):
        entry_list.append({
            "name": e.name,
            "idx": e.idx,
            "entry_date": str(e.entry_date) if e.entry_date else None,
            "start_time": str(e.start_time) if e.start_time else None,
            "end_time": str(e.end_time) if e.end_time else None,
            "duration_hours": e.duration_hours,
            "minutes": e.get("minutes"),
            "activity": e.get("activity"),
            "notes": e.notes,
            "is_running": bool(e.get("is_running")),
        })

    # This user's own slice of the total, separate from the whole team's
    # combined total_hours (unchanged, still computed by _recalc_total_hours
    # over every entry regardless of who punched it).
    personal_hours = round(
        sum(flt(e.duration_hours) for e in my_entries if not e.get("is_running")), 2
    )

    # This is a single lookup on the already-detail view (get_timesheet),
    # not the paginated list, so it's not a cost that scales with the
    # number of timesheets — worth calling out since that's exactly the
    # kind of thing that was slow before the list/stats rewrite.
    wih_photo = None
    if doc.get("wih_number"):
        wih_photo = frappe.db.get_value("Work In Hand", doc.wih_number, "photos")

    # Only a Timesheet Manager needs (or should see) who else still has a
    # timer running — everyone else just sees their own timer as before.
    # Scoped to Draft docs only: once submitted there's nothing left to
    # block, and doc.timesheet_entry's is_running flags are frozen anyway.
    is_manager = _is_timesheet_manager(user)
    running_timer_users = _running_timer_users(doc) if (is_manager and doc.docstatus == 0) else []

    return {
        "name": doc.name,
        "wih_number": doc.get("wih_number"),
        "wih_photo": wih_photo,
        "employee": doc.user or "",
        "employee_name": doc.user,
        "product_name": doc.get("product_name"),
        "start_date": str(doc.start_date) if doc.get("start_date") else None,
        "end_date": str(doc.end_date) if doc.get("end_date") else None,
        "status": _status_label(doc.docstatus),
        "docstatus": doc.docstatus,
        "total_hours": doc.get("total_hours"),   # whole-team combined total
        "personal_hours": personal_hours,          # this viewer's own total
        # Set only at submit time, by a Timesheet Manager — the figure
        # they confirmed, which may differ from total_hours above. Blank
        # until submission; shown on the frontend as "Final Hrs (as per
        # Supervisor)" once present.
        "final_hrs": doc.get("final_hrs"),
        "notes": doc.get("notes"),
        "timesheet_entry": entry_list,             # only this viewer's own rows
        "active_timer_started_at": active_timer_started_at,
        "active_timer_elapsed_hours": active_timer_elapsed_hours,
        "is_timesheet_manager": is_manager,
        "running_timer_users": running_timer_users,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def reset_session():
    """Called (as a GET request) right before login(). GET requests are
    never CSRF-checked by Frappe, so this can safely clear out any
    pre-existing session cookie in the browser — e.g. an ERPNext Desk
    session left over from logging in elsewhere on the same device/
    browser, or a previous kiosk user's session on a shared tablet.

    Without this, login() (a POST request) can get rejected with
    "Invalid Request" (CSRFTokenError) whenever the browser still holds
    a valid sid cookie for a *different* authenticated session — the
    login POST looks, to Frappe, like an attempted request against that
    other session rather than a fresh Guest login.
    """
    if frappe.session.user != "Guest":
        frappe.local.login_manager.logout()
        frappe.db.commit()
    return {"ok": True}


@frappe.whitelist(allow_guest=True)
def login(usr=None, pwd=None, username=None, password=None):
    """Equivalent of POST /auth/login. No Employee lookup required."""
    usr = usr or username
    pwd = pwd or password
    if not usr or not pwd:
        frappe.throw("Username and password are required.")

    login_manager = LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)
    login_manager.post_login()
    frappe.db.commit()

    # employeeId/employeeName are kept only for API-shape compatibility with
    # the existing frontend types; both simply mirror the username.
    #
    # csrf_token: login() creates a brand new session, which invalidates any
    # CSRF token the page may have picked up while it was still a Guest
    # session. Returning the fresh token here lets the SPA keep going
    # without a full page reload.
    return {
        "userId": usr,
        "employeeId": usr,
        "employeeName": usr,
        "csrf_token": frappe.sessions.get_csrf_token(),
        "isTimesheetManager": _is_timesheet_manager(usr),
    }


@frappe.whitelist()
def get_current_user():
    """Equivalent of GET /auth/me"""
    user = _current_user()
    return {
        "userId": user,
        "employeeId": user,
        "employeeName": user,
        "isTimesheetManager": _is_timesheet_manager(user),
    }


@frappe.whitelist()
def logout():
    """Equivalent of POST /auth/logout"""
    frappe.local.login_manager.logout()
    frappe.db.commit()
    return {"message": "Logged out"}


# ---------------------------------------------------------------------------
# Employees (kept for parity; not used by the login/session flow anymore)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_employees():
    return frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "designation", "department"],
        order_by="employee_name asc",
        limit_page_length=500,
    )


# ---------------------------------------------------------------------------
# Work In Hand (WIH) — sourced from this user's Timesheet Allocation
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_wih(search=None):
    user = _current_user()

    allocated_wih = list(dict.fromkeys(_allocated_wih_numbers(user)))  # de-dup, preserve order

    if allocated_wih:
        # Exclude WIH that ALREADY have an open (Draft) or Submitted
        # Employee Timesheet — for ANY user, not just this one. A WIH's
        # timesheet is a single document shared by everyone allocated to
        # it, so if one already exists the right move is to open it from
        # the dashboard, not start a second, competing one from here.
        existing = frappe.get_all(
            TS_DOCTYPE,
            filters={"wih_number": ["in", allocated_wih], "docstatus": ["in", [0, 1]]},
            pluck="wih_number",
            limit_page_length=500,
        )
        used_wih = {w for w in existing if w}
        allocated_wih = [w for w in allocated_wih if w not in used_wih]

    # Optional search filter (case-insensitive substring match)
    if search:
        s = search.lower()
        allocated_wih = [w for w in allocated_wih if s in w.lower()]

    # client_code powers the Style Code field on the New Timesheet screen —
    # fetched here (once, in bulk) rather than the frontend calling back
    # per-selection, since the whole allocated list is already small and
    # already being sent down.
    client_codes = {}
    if allocated_wih:
        rows = frappe.get_all(
            "Work In Hand", filters={"name": ["in", allocated_wih]}, fields=["name", "client_code"]
        )
        client_codes = {r.name: r.client_code for r in rows}

    return [
        {"name": w, "product_name": None, "status": None, "client_code": client_codes.get(w)}
        for w in allocated_wih
    ]


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------

def _running_timesheet_names(ts_names, user):
    """Which of `ts_names` (Employee Timesheet names) currently have a
    running timer belonging to `user` — powers the small green "running"
    dot on the dashboard list. Scoped to just the page of names already
    being displayed (never the whole table), so it stays a cheap add-on
    rather than reopening the N+1-full-document-load problem the list/stats
    rewrite fixed.

    Same lenient _is_mine philosophy as everywhere else: a running row with
    no owner recorded counts as this user's too. If the `user` column
    doesn't exist yet, this can't be scoped to a specific person at all, so
    it fails closed (no dot shown) rather than showing everyone's dot to
    everyone.
    """
    if not ts_names or not _entry_user_field_exists():
        return set()
    rows = frappe.db.sql(
        """
        select distinct te.parent
        from `tabTimesheet Entry` te
        where te.parenttype = 'Employee Timesheet'
          and te.parent in %(names)s
          and te.is_running = 1
          and (te.user = %(user)s or te.user is null or te.user = '')
        """,
        {"names": tuple(ts_names), "user": user},
    )
    return {r[0] for r in rows}


@frappe.whitelist()
def list_timesheets(status=None, wih_number=None, page=1):
    """"My Timesheets" now means: timesheets for a WIH I'm currently
    allocated to (the common case — since a WIH is shared by a team, this
    also surfaces timesheets a teammate started), UNIONed with any
    timesheet I personally created, so nobody loses visibility into a
    timesheet they started just because their allocation later changes.

    Still a single lightweight query rather than loading full documents —
    the list view only needs these summary fields.
    """
    user = _current_user()
    page = max(1, int(page or 1))
    start = (page - 1) * PAGE_SIZE

    allocated = _allocated_wih_numbers(user)

    values = {"user": user}
    if allocated:
        values["allocated"] = tuple(allocated)
        scope_clause = "(ts.wih_number in %(allocated)s or ts.user = %(user)s)"
    else:
        scope_clause = "(ts.user = %(user)s)"

    status_clause = ""
    if status == "Draft":
        status_clause = "and ts.docstatus = 0"
    elif status == "Submitted":
        status_clause = "and ts.docstatus = 1"
    else:
        # "All" means every non-Cancelled timesheet (Draft + Submitted) —
        # a Cancelled Employee Timesheet is a voided document and
        # shouldn't clutter a list the user is actively working from.
        status_clause = "and ts.docstatus != 2"

    search_clause = ""
    if wih_number:
        # Substring search, not exact match, so users can type a partial
        # WIH number and find it.
        search_clause = "and ts.wih_number like %(search)s"
        values["search"] = f"%{wih_number}%"

    total = frappe.db.sql(
        f"""
        select count(*) from `tabEmployee Timesheet` ts
        where {scope_clause} {status_clause} {search_clause}
        """,
        values,
    )[0][0]

    items = frappe.db.sql(
        f"""
        select
            ts.name, ts.wih_number, ts.product_name, ts.start_date, ts.end_date,
            ts.docstatus, ts.total_hours, ts.notes
        from `tabEmployee Timesheet` ts
        where {scope_clause} {status_clause} {search_clause}
        order by ts.modified desc
        limit %(page_size)s offset %(start)s
        """,
        {**values, "page_size": PAGE_SIZE, "start": start},
        as_dict=True,
    )

    running_names = _running_timesheet_names([i["name"] for i in items], user)
    for item in items:
        item["is_running_for_me"] = item["name"] in running_names
        # See _status_label's docstring — never trust the stored `status`
        # field directly, since a submit/cancel done straight from the
        # ERPNext desk UI only touches docstatus, not that custom field.
        item["status"] = _status_label(item["docstatus"])

    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}


@frappe.whitelist()
def create_timesheet(wih_number, product_name=None, start_date=None, end_date=None):
    user = _current_user()

    # If a shared open timesheet already exists for this WIH (created by
    # anyone), join it instead of creating a duplicate — mirrors the
    # exclusion list_wih applies before this screen is even shown, but
    # kept here too as a defensive check against direct API calls.
    existing = frappe.db.get_value(
        TS_DOCTYPE, {"wih_number": wih_number, "docstatus": ["in", [0, 1]]}
    )
    if existing:
        doc = frappe.get_doc(TS_DOCTYPE, existing)
        # Core Frappe permissions (e.g. a User Permission restricting the
        # Employee link field) don't know about the WIH-sharing model —
        # _check_access is the real gate here, so core checks are bypassed
        # for the rest of this request. See the same comment on the other
        # mutating functions below for the full rationale.
        doc.flags.ignore_permissions = True
        _check_access(doc, user)
        return _build_timesheet_response(doc)

    doc = frappe.new_doc(TS_DOCTYPE)
    doc.flags.ignore_permissions = True
    doc.wih_number = wih_number
    doc.user = user
    doc.product_name = product_name
    doc.start_date = start_date or today()
    doc.end_date = end_date
    doc.status = "Draft"
    doc.total_hours = 0
    doc.insert()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def get_timesheet(name):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    _check_access(doc)
    if doc.docstatus == 2:
        # Cancelled documents are voided — list_timesheets/get_timesheet_stats
        # already exclude them from every list and count, but a direct link
        # or a stale bookmark could still land here, so block it explicitly
        # rather than rendering a timer screen for a document that no
        # longer exists in any meaningful sense.
        frappe.throw("This timesheet has been cancelled.", frappe.DoesNotExistError)
    return _build_timesheet_response(doc)


@frappe.whitelist()
def update_timesheet(name, product_name=None, start_date=None, end_date=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # Bypass Frappe's core permission engine (e.g. Employee-link User
    # Permissions) — a shared WIH timesheet's real access rule is
    # _check_access below, which already accounts for teammates sharing one
    # document. Core checks don't know about that sharing model and would
    # otherwise block a teammate whose own Employee record differs from
    # whoever's Employee is stamped on this doc.
    doc.flags.ignore_permissions = True
    _check_access(doc)
    if product_name is not None:
        doc.product_name = product_name
    if start_date is not None:
        doc.start_date = start_date
    if end_date is not None:
        doc.end_date = end_date
    if notes is not None:
        doc.notes = notes
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def submit_timesheet(name, final_hrs=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # See update_timesheet's comment — _check_access is the real gate for a
    # shared timesheet; core perms (incl. submit-level ones) are bypassed.
    doc.flags.ignore_permissions = True
    user = _current_user()
    _check_access(doc, user)

    # Submitting locks the shared document for the WHOLE team, not just
    # this user, so only a Timesheet Manager may do it. Everyone else can
    # still freely log/edit their own entries (plain doc.save(), untouched
    # by this) — they just can't take the final lock-and-submit step.
    if not _is_timesheet_manager(user):
        frappe.throw(
            "Only a Timesheet Manager can submit this timesheet. "
            "You can still add or edit your own time entries.",
            frappe.PermissionError,
        )

    # Checked across EVERY entry on the document (not just this user's
    # own), since submitting locks the shared timesheet for the whole
    # team — if a teammate's timer is still running, submitting now would
    # freeze their punch mid-run. The timer screen already shows the
    # manager this same running list (via running_timer_users on
    # get_timesheet) before they ever open the submit dialog; this is the
    # server-side backstop in case a timer started in the gap between
    # loading that screen and clicking submit.
    running = _running_timer_users(doc)
    if running or any(e.get("is_running") for e in doc.timesheet_entry):
        names = ", ".join(r["full_name"] for r in running) or "a teammate"
        frappe.throw(f"Cannot submit — timer still running for: {names}. Ask them to stop it first.")

    final_hrs = flt(final_hrs)
    if final_hrs <= 0:
        frappe.throw("Enter the final hours (as confirmed by the supervisor) before submitting.")

    # This is a separate, supervisor-confirmed figure — it does NOT
    # recompute or overwrite total_hours (the raw sum of logged entries),
    # it's stored alongside it and is what the app displays back as
    # "Final Hrs (as per Supervisor)" once submitted.
    doc.final_hrs = final_hrs
    doc.status = "Submitted"
    doc.save()
    doc.submit()

    # Mirrored onto the linked WIH so anything elsewhere in ERPNext that
    # reads Work In Hand directly (rather than through this app) sees the
    # same confirmed figure.
    if doc.get("wih_number"):
        frappe.db.set_value("Work In Hand", doc.wih_number, "final_hrs", final_hrs)

    frappe.db.commit()
    return _build_timesheet_response(doc)


# --- Timer -------------------------------------------------------------

@frappe.whitelist()
def start_timer(name, activity=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # See update_timesheet's comment — _check_access is the real gate.
    doc.flags.ignore_permissions = True
    user = _current_user()
    _check_access(doc, user)

    # Scoped to THIS user's own entries — several teammates can each have
    # an independent timer running on the same shared timesheet at once.
    # Uses the same lenient _is_mine match as everywhere else (not a strict
    # e.get("user") == user), so this still works correctly even for a row
    # whose `user` never got saved.
    if any(e.get("is_running") and _is_mine(e, user) for e in doc.timesheet_entry):
        frappe.throw("A timer is already running. Stop it before starting a new one.")

    activity = (activity or "").strip()
    if not activity:
        frappe.throw("Please select an activity before starting the timer.")

    now = now_datetime()
    doc.append("timesheet_entry", {
        "entry_date": now.date(),
        "start_time": now,
        "end_time": None,
        "duration_hours": 0,
        "minutes": 0,
        "activity": activity,
        "notes": notes,
        "is_running": 1,
        "user": user,
    })
    # THE FIX: this call was missing here (stop_timer/add_entry/etc. all
    # had it). total_hours is a field this app maintains itself — nothing
    # in core Frappe recalculates it — so saving a fresh timer-start entry
    # without refreshing it first was writing back a stale/blank value on
    # top of whatever was correctly saved before. That showed up as TEAM
    # TOTAL reading "0 Hrs 0 Mins" the moment a timer started, even though
    # the team already had hours logged, while MY HOURS stayed correct
    # because personal_hours is always computed fresh in
    # _build_timesheet_response rather than read from a stored field.
    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def get_activity_options():
    """Select-field options for Timesheet Entry.activity, resolved from
    DocType metadata at runtime rather than hardcoded here — same
    reasoning as _allocated_wih_numbers: this keeps working with no code
    change if the option list is ever edited via Customize Form, and
    degrades to an empty list rather than erroring if the field doesn't
    exist yet on a given site.
    """
    meta = frappe.get_meta("Timesheet Entry")
    field = meta.get_field("activity")
    if not field or not field.options:
        return []
    return [o.strip() for o in field.options.split("\n") if o.strip()]


@frappe.whitelist()
def stop_timer(name, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # See update_timesheet's comment — _check_access is the real gate.
    doc.flags.ignore_permissions = True
    user = _current_user()
    _check_access(doc, user)

    # Must match on user too — with several teammates possibly running
    # timers at once on the shared timesheet, "the" active entry is
    # ambiguous without scoping to this specific user's own row. Uses the
    # same lenient _is_mine match start_timer's duplicate check uses — this
    # is the actual fix for "Stop Timer" doing nothing: if `user` never got
    # saved on the row (see _entry_user_field_exists above), a strict
    # e.get("user") == user match here can never find it, even though the
    # entry visibly shows as running for you.
    active = next(
        (e for e in doc.timesheet_entry if e.get("is_running") and _is_mine(e, user)),
        None,
    )
    if not active:
        frappe.throw("No active timer found for you on this timesheet.")

    now = now_datetime()
    duration = round(time_diff_in_hours(now, active.start_time), 4)

    active.end_time = now
    active.duration_hours = duration
    active.minutes = round(duration * 60, 2)
    active.is_running = 0
    # Backfills a blank owner on stop, in addition to start_timer already
    # setting it on creation — belt-and-suspenders in case the field wasn't
    # actually saving yet when this row was first punched.
    active.user = user
    if notes is not None:
        active.notes = notes

    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


# --- Manual entries ------------------------------------------------------

@frappe.whitelist()
def add_entry(name, entry_date, start_time, end_time, duration_hours=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # See update_timesheet's comment — _check_access is the real gate.
    doc.flags.ignore_permissions = True
    user = _current_user()
    _check_access(doc, user)

    full_start = f"{entry_date} {start_time}"
    full_end = f"{entry_date} {end_time}"

    if duration_hours is None:
        duration_hours = round(time_diff_in_hours(full_end, full_start), 4)
    if flt(duration_hours) <= 0:
        frappe.throw("End time must be after start time.")

    doc.append("timesheet_entry", {
        "entry_date": entry_date,
        "start_time": full_start,
        "end_time": full_end,
        "duration_hours": duration_hours,
        "minutes": round(float(duration_hours) * 60, 2),
        "notes": notes or "Manual entry",
        "is_running": 0,
        "user": user,
    })
    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def update_entry(name, idx, entry_date=None, start_time=None, end_time=None, duration_hours=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # See update_timesheet's comment — _check_access is the real gate.
    doc.flags.ignore_permissions = True
    user = _current_user()
    _check_access(doc, user)

    if doc.docstatus != 0:
        frappe.throw("Cannot edit entries on a submitted timesheet.")

    idx = int(idx)
    row = next((e for e in doc.timesheet_entry if e.idx == idx), None)
    if not row:
        frappe.throw("Entry not found", frappe.DoesNotExistError)
    # Legacy rows punched before the `user` field existed have no owner
    # recorded, so they're left editable rather than locked for everyone.
    if not _is_mine(row, user):
        frappe.throw("You can only edit your own time entries.", frappe.PermissionError)
    # Editing start/end on a live running row would fight with stop_timer's
    # own end_time/duration calculation — make them stop it first.
    if row.get("is_running") and (start_time is not None or end_time is not None):
        frappe.throw("Stop the timer before editing its start or end time.")

    if entry_date is not None:
        row.entry_date = entry_date
    if start_time is not None:
        row.start_time = start_time
    if end_time is not None:
        row.end_time = end_time

    if duration_hours is not None:
        row.duration_hours = duration_hours
        row.minutes = round(float(duration_hours) * 60, 2)
    elif start_time is not None or end_time is not None:
        # Recompute whenever either side of the pair changes — not just
        # when both are supplied in the same call — since the click-to-edit
        # time cells on the frontend only ever send ONE of start_time/
        # end_time at a time (whichever cell was clicked), letting the
        # other side stand as already stored on the row.
        if not row.start_time or not row.end_time:
            frappe.throw("Both start and end time are required.")
        duration = round(time_diff_in_hours(row.end_time, row.start_time), 4)
        if flt(duration) <= 0:
            frappe.throw("End time must be after start time.")
        row.duration_hours = duration
        row.minutes = round(duration * 60, 2)

    if notes is not None:
        row.notes = notes

    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def delete_entry(name, idx):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    # See update_timesheet's comment — _check_access is the real gate.
    doc.flags.ignore_permissions = True
    user = _current_user()
    _check_access(doc, user)

    idx = int(idx)
    row = next((e for e in doc.timesheet_entry if e.idx == idx), None)
    if not row:
        frappe.throw("Entry not found", frappe.DoesNotExistError)
    if not _is_mine(row, user):
        frappe.throw("You can only delete your own time entries.", frappe.PermissionError)

    doc.timesheet_entry = [e for e in doc.timesheet_entry if e.idx != idx]

    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


# --- Stats -----------------------------------------------------------------

@frappe.whitelist()
def get_timesheet_stats():
    """Was previously loading up to 20 full Employee Timesheet documents
    (each pulling its entire Timesheet Entry child table) on every single
    dashboard visit — the most expensive call in the app, and one every
    user hits every time they land on the dashboard. Replaced with two
    aggregate SQL queries that return the exact same numbers regardless of
    how many timesheets a user has (the old version was also silently
    wrong for anyone with more than 20 timesheets, since it only looked at
    the most recent 20).

    Scope for "my timesheets" matches list_timesheets: WIH I'm allocated
    to, unioned with ones I created. HOURS TODAY and the running-timer flag
    are further scoped to entries *this user personally punched*
    (te.user), since those numbers should read as personal effort, not the
    whole team's combined time — total_hours (the team figure) is shown on
    the timer screen itself instead.

    That te.user scoping is only added to the SQL below if the column
    genuinely exists on Timesheet Entry (_entry_user_field_exists). Unlike
    the doc-object `.get("user")` used elsewhere in this file, which just
    returns None for a field that isn't there, referencing a column that
    doesn't exist in raw SQL is a hard database error — and that error was
    silently swallowed by the dashboard's stats loader, which is why the
    stat cards were stuck showing "…" instead of an error. If the column
    is missing, personal figures degrade to 0 rather than crashing the
    whole dashboard (accurate once you add the field — see
    DOCTYPE_REQUIREMENTS.md).

    pending_timesheets counts WIH numbers this user is currently allocated
    to (via Timesheet Allocation) for which no Draft or Submitted Employee
    Timesheet exists yet — i.e. WIH that have been assigned but nobody has
    started logging time against at all. A Cancelled timesheet doesn't
    count as "created" for this purpose, so a WIH whose only timesheet was
    cancelled is still counted as pending.
    """
    user = _current_user()
    today_str = today()

    allocated = _allocated_wih_numbers(user)
    values = {"user": user}
    if allocated:
        values["allocated"] = tuple(allocated)
        scope_clause = "(ts.wih_number in %(allocated)s or ts.user = %(user)s)"
    else:
        scope_clause = "(ts.user = %(user)s)"

    counts = frappe.db.sql(
        f"""
        select
            count(*) as total,
            sum(case when docstatus = 0 then 1 else 0 end) as active,
            sum(case when docstatus = 1 then 1 else 0 end) as submitted
        from `tabEmployee Timesheet` ts
        where {scope_clause} and ts.docstatus != 2
        """,
        values,
        as_dict=True,
    )[0]

    wih_with_timesheet = set()
    if allocated:
        wih_with_timesheet = set(frappe.get_all(
            TS_DOCTYPE,
            filters={"wih_number": ["in", allocated], "docstatus": ["in", [0, 1]]},
            pluck="wih_number",
            limit_page_length=0,
        ))
    pending_timesheets = len(set(allocated) - wih_with_timesheet)

    hours_values = dict(values)
    hours_values["today"] = today_str

    # "and 1 = 0" rather than just dropping the clause: if the column is
    # missing, these figures should read as 0 (unknown), not silently
    # widen into a team-wide total mislabeled as personal.
    user_scope = "and te.user = %(user)s" if _entry_user_field_exists() else "and 1 = 0"

    hours = frappe.db.sql(
        f"""
        select
            coalesce(sum(case when te.entry_date = %(today)s and te.is_running = 0 {user_scope} then te.duration_hours else 0 end), 0) as today_hours,
            sum(case when te.is_running = 1 {user_scope} then 1 else 0 end) as running_count
        from `tabTimesheet Entry` te
        inner join `tabEmployee Timesheet` ts on ts.name = te.parent
        where {scope_clause} and ts.docstatus != 2 and te.parenttype = 'Employee Timesheet'
        """,
        hours_values,
        as_dict=True,
    )[0]

    return {
        "total_timesheets": int(counts.total or 0),
        "active_timesheets": int(counts.active or 0),
        "submitted_timesheets": int(counts.submitted or 0),
        "pending_timesheets": pending_timesheets,
        "total_hours_today": round(flt(hours.today_hours), 2),
        "has_active_timer": bool(hours.running_count),
    }


# --- My Timesheet report ----------------------------------------------------

@frappe.whitelist()
def get_my_timesheet_report(from_date=None, to_date=None, wih_number=None, status=None):
    """Powers the "My Timesheet" report screen — one row per (date, WIH)
    this user personally logged time against, e.g.
    "01-Sep-26 / WIH-0000005 / 5.5 hrs". Only THIS user's own hours (not
    the whole shared timesheet's team total).

    Date range and WIH search are independent filters and both optional —
    at least one is required (the frontend only calls this once the user
    has actually chosen a filter, rather than dumping the user's whole
    history unfiltered): a WIH search with no date range covers all time
    for that WIH; a date range with no WIH search covers every WIH in
    that window; both together narrow to their intersection.

    from_date/to_date must both be given to apply a date filter — one
    without the other is treated as "no range chosen" and ignored, rather
    than guessing an open-ended bound.

    wih_number is a substring match (case-sensitive per MySQL's default
    collation, same as list_timesheets' WIH search), not an exact one, so
    a partial WIH number still finds it.

    Grouped by (entry_date, et.name) rather than (entry_date, wih_number)
    — equivalent in practice (a WIH has at most one open/submitted
    Employee Timesheet at a time, per list_wih's exclusion rule) but this
    way et.name — needed for the frontend's click-through to that
    timesheet — falls straight out of the group by, rather than needing a
    second lookup per row.

    A fresh lean SQL aggregate rather than looping frappe.get_doc per row,
    same reasoning as get_timesheet_stats/list_timesheets: a wide date
    range can span many rows, and this is a report a user may run often.

    status: None/"All" -> Draft + Submitted (never Cancelled). "Draft" ->
    docstatus 0 only. "Submitted" -> docstatus 1 only.
    """
    user = _current_user()
    wih_number = (wih_number or "").strip()
    has_range = bool(from_date) and bool(to_date)
    has_wih = bool(wih_number)
    if not has_range and not has_wih:
        frappe.throw("Select a date range or search by WIH number to generate the report.")

    if status == "Draft":
        status_clause = "and et.docstatus = 0"
    elif status == "Submitted":
        status_clause = "and et.docstatus = 1"
    else:
        status_clause = "and et.docstatus in (0, 1)"

    date_clause = "and te.entry_date between %(from_date)s and %(to_date)s" if has_range else ""
    wih_clause = "and et.wih_number like %(wih)s" if has_wih else ""

    # Same fail-closed reasoning as _running_timesheet_names: without the
    # `user` column there's no reliable way to scope this to "my" entries
    # specifically, so an empty report is safer than one that quietly
    # shows everyone's hours as if they were this user's own.
    if not _entry_user_field_exists():
        return []

    values = {"user": user}
    if has_range:
        values["from_date"] = from_date
        values["to_date"] = to_date
    if has_wih:
        values["wih"] = f"%{wih_number}%"

    rows = frappe.db.sql(
        f"""
        select
            et.name,
            te.entry_date,
            et.wih_number,
            et.product_name,
            et.status,
            et.docstatus,
            et.final_hrs,
            sum(te.duration_hours) as day_hours
        from `tabTimesheet Entry` te
        inner join `tabEmployee Timesheet` et on et.name = te.parent
        where te.parenttype = 'Employee Timesheet'
          and (te.is_running = 0 or te.is_running is null)
          and (te.user = %(user)s or te.user is null or te.user = '')
          {date_clause}
          {wih_clause}
          {status_clause}
        group by te.entry_date, et.name
        order by te.entry_date desc, et.wih_number
        """,
        values,
        as_dict=True,
    )

    return [
        {
            "name": r.name,
            "entry_date": str(r.entry_date) if r.entry_date else None,
            "wih_number": r.wih_number,
            "product_name": r.product_name,
            "status": _status_label(r.docstatus),
            "docstatus": r.docstatus,
            "final_hrs": r.final_hrs,
            "hours": round(flt(r.day_hours), 2),
        }
        for r in rows
    ]
