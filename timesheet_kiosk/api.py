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
from frappe.utils import today, add_days, now_datetime, time_diff_in_hours, flt

TS_DOCTYPE = "Employee Timesheet"
ALLOCATION_DOCTYPE = "Timesheet Allocation"
PAGE_SIZE = 10


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


def _recalc_total_hours(doc):
    doc.total_hours = round(sum(flt(e.duration_hours) for e in doc.timesheet_entry), 2)


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

    return {
        "name": doc.name,
        "wih_number": doc.get("wih_number"),
        "wih_photo": wih_photo,
        "employee": doc.user or "",
        "employee_name": doc.user,
        "product_name": doc.get("product_name"),
        "start_date": str(doc.start_date) if doc.get("start_date") else None,
        "end_date": str(doc.end_date) if doc.get("end_date") else None,
        "status": doc.status or "Draft",
        "docstatus": doc.docstatus,
        "total_hours": doc.get("total_hours"),   # whole-team combined total
        "personal_hours": personal_hours,          # this viewer's own total
        "notes": doc.get("notes"),
        "timesheet_entry": entry_list,             # only this viewer's own rows
        "active_timer_started_at": active_timer_started_at,
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
    }


@frappe.whitelist()
def get_current_user():
    """Equivalent of GET /auth/me"""
    user = _current_user()
    return {"userId": user, "employeeId": user, "employeeName": user}


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

    return [{"name": w, "product_name": None, "status": None} for w in allocated_wih]


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------

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
            ts.status, ts.docstatus, ts.total_hours, ts.notes
        from `tabEmployee Timesheet` ts
        where {scope_clause} {status_clause} {search_clause}
        order by ts.modified desc
        limit %(page_size)s offset %(start)s
        """,
        {**values, "page_size": PAGE_SIZE, "start": start},
        as_dict=True,
    )

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
        _check_access(doc, user)
        return _build_timesheet_response(doc)

    doc = frappe.new_doc(TS_DOCTYPE)
    doc.wih_number = wih_number
    doc.user = user
    doc.product_name = product_name
    doc.start_date = start_date or today()
    doc.end_date = end_date
    doc.status = "Draft"
    doc.insert()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def get_timesheet(name):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    _check_access(doc)
    return _build_timesheet_response(doc)


@frappe.whitelist()
def update_timesheet(name, product_name=None, start_date=None, end_date=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
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
def submit_timesheet(name):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    _check_access(doc)

    # Checked across EVERY entry on the document (not just this user's
    # own), since submitting locks the shared timesheet for the whole
    # team — if a teammate's timer is still running, submitting now would
    # freeze their punch mid-run.
    if any(e.get("is_running") for e in doc.timesheet_entry):
        frappe.throw("Stop the running timer before submitting the timesheet.")

    doc.status = "Submitted"
    doc.save()
    doc.submit()
    frappe.db.commit()
    return _build_timesheet_response(doc)


# --- Timer -------------------------------------------------------------

@frappe.whitelist()
def start_timer(name, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    user = _current_user()
    _check_access(doc, user)

    # Scoped to THIS user's own entries — several teammates can each have
    # an independent timer running on the same shared timesheet at once.
    # Uses the same lenient _is_mine match as everywhere else (not a strict
    # e.get("user") == user), so this still works correctly even for a row
    # whose `user` never got saved.
    if any(e.get("is_running") and _is_mine(e, user) for e in doc.timesheet_entry):
        frappe.throw("A timer is already running. Stop it before starting a new one.")

    now = now_datetime()
    doc.append("timesheet_entry", {
        "entry_date": now.date(),
        "start_time": now,
        "end_time": None,
        "duration_hours": 0,
        "minutes": 0,
        "notes": notes,
        "is_running": 1,
        "user": user,
    })
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def stop_timer(name, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
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
    user = _current_user()
    _check_access(doc, user)

    idx = int(idx)
    row = next((e for e in doc.timesheet_entry if e.idx == idx), None)
    if not row:
        frappe.throw("Entry not found", frappe.DoesNotExistError)
    # Legacy rows punched before the `user` field existed have no owner
    # recorded, so they're left editable rather than locked for everyone.
    if not _is_mine(row, user):
        frappe.throw("You can only edit your own time entries.", frappe.PermissionError)

    if entry_date is not None:
        row.entry_date = entry_date
    if start_time is not None:
        row.start_time = start_time
    if end_time is not None:
        row.end_time = end_time

    if duration_hours is not None:
        row.duration_hours = duration_hours
        row.minutes = round(float(duration_hours) * 60, 2)
    elif start_time is not None and end_time is not None:
        row.duration_hours = round(time_diff_in_hours(row.end_time, row.start_time), 4)
        row.minutes = round(row.duration_hours * 60, 2)

    if notes is not None:
        row.notes = notes

    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def delete_entry(name, idx):
    doc = frappe.get_doc(TS_DOCTYPE, name)
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
    to, unioned with ones I created. HOURS TODAY/WEEK and the running-timer
    flag are further scoped to entries *this user personally punched*
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
    """
    user = _current_user()
    today_str = today()
    week_ago_str = add_days(today_str, -7)

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
        where {scope_clause}
        """,
        values,
        as_dict=True,
    )[0]

    hours_values = dict(values)
    hours_values["today"] = today_str
    hours_values["week_ago"] = week_ago_str

    # "and 1 = 0" rather than just dropping the clause: if the column is
    # missing, these figures should read as 0 (unknown), not silently
    # widen into a team-wide total mislabeled as personal.
    user_scope = "and te.user = %(user)s" if _entry_user_field_exists() else "and 1 = 0"

    hours = frappe.db.sql(
        f"""
        select
            coalesce(sum(case when te.entry_date = %(today)s and te.is_running = 0 {user_scope} then te.duration_hours else 0 end), 0) as today_hours,
            coalesce(sum(case when te.entry_date >= %(week_ago)s and te.is_running = 0 {user_scope} then te.duration_hours else 0 end), 0) as week_hours,
            sum(case when te.is_running = 1 {user_scope} then 1 else 0 end) as running_count
        from `tabTimesheet Entry` te
        inner join `tabEmployee Timesheet` ts on ts.name = te.parent
        where {scope_clause} and te.parenttype = 'Employee Timesheet'
        """,
        hours_values,
        as_dict=True,
    )[0]

    return {
        "total_timesheets": int(counts.total or 0),
        "active_timesheets": int(counts.active or 0),
        "submitted_timesheets": int(counts.submitted or 0),
        "total_hours_today": round(flt(hours.today_hours), 2),
        "total_hours_week": round(flt(hours.week_hours), 2),
        "has_active_timer": bool(hours.running_count),
    }
