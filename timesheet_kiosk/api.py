# -*- coding: utf-8 -*-
"""
Timesheet Kiosk API (v3)
-------------------------
Python port of the current Express routes (auth, employees, wih, timesheets).

v3 fixes a schema drift from v2: the live `Timesheet Entry` doctype uses a
field called `minutes` (Float) and an explicit `is_running` (Check) field —
NOT `duration_minutes`, which v2 wrote to. Since Frappe silently drops
values for fields that don't exist on a doctype, v2's minutes values and
"is running" state were never actually being persisted. Fixed here, and
`total_hours` on the parent is now recalculated server-side on every
mutation instead of being left for the caller to maintain.

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


def _check_owner(doc):
    if doc.user != frappe.session.user:
        frappe.throw("You are not permitted to access this timesheet.", frappe.PermissionError)


def _recalc_total_hours(doc):
    doc.total_hours = round(sum(flt(e.duration_hours) for e in doc.timesheet_entry), 2)


def _build_timesheet_response(doc):
    entries = doc.get("timesheet_entry") or []
    # is_running is the source of truth; fall back to the old heuristic
    # (start_time set, end_time blank) in case of pre-fix legacy rows.
    active_entry = next(
        (e for e in entries if e.get("is_running") or (e.start_time and not e.end_time)),
        None,
    )
    active_timer_started_at = None
    if active_entry:
        active_timer_started_at = str(active_entry.start_time).replace(" ", "T")

    entry_list = []
    for e in entries:
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

    return {
        "name": doc.name,
        "wih_number": doc.get("wih_number"),
        "employee": doc.user or "",
        "employee_name": doc.user,
        "product_name": doc.get("product_name"),
        "start_date": str(doc.start_date) if doc.get("start_date") else None,
        "end_date": str(doc.end_date) if doc.get("end_date") else None,
        "status": doc.status or "Draft",
        "docstatus": doc.docstatus,
        "total_hours": doc.get("total_hours"),
        "notes": doc.get("notes"),
        "timesheet_entry": entry_list,
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

    # 1. WIH numbers already used by an open (Draft) or Submitted timesheet
    #    belonging to THIS user.
    existing = frappe.get_all(
        TS_DOCTYPE,
        filters={"user": user, "docstatus": ["in", [0, 1]]},
        pluck="wih_number",
        limit_page_length=500,
    )
    used_wih = {w for w in existing if w}

    # 2. WIH numbers allocated to this user via Timesheet Allocation.
    allocation_names = frappe.get_all(
        ALLOCATION_DOCTYPE, filters={"user": user}, pluck="name", limit_page_length=50
    )

    allocated_wih = []
    for name in allocation_names:
        alloc_doc = frappe.get_doc(ALLOCATION_DOCTYPE, name)
        for row in (alloc_doc.get("wih") or []):
            wih_value = row.get("wih") or row.name
            if wih_value:
                allocated_wih.append(wih_value)

    # Deduplicate, preserving order
    allocated_wih = list(dict.fromkeys(allocated_wih))

    # 3. Exclude WIHs already used by this user
    allocated_wih = [w for w in allocated_wih if w not in used_wih]

    # 4. Optional search filter (case-insensitive substring match)
    if search:
        s = search.lower()
        allocated_wih = [w for w in allocated_wih if s in w.lower()]

    return [{"name": w, "product_name": None, "status": None} for w in allocated_wih]


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_timesheets(status=None, wih_number=None, page=1):
    user = _current_user()
    page = max(1, int(page or 1))
    start = (page - 1) * PAGE_SIZE

    filters = {"user": user}
    if status == "Draft":
        filters["docstatus"] = 0
    elif status == "Submitted":
        filters["docstatus"] = 1
    if wih_number:
        filters["wih_number"] = wih_number

    names = frappe.get_all(
        TS_DOCTYPE,
        filters=filters,
        pluck="name",
        order_by="modified desc",
        limit_page_length=PAGE_SIZE,
        limit_start=start,
    )
    return [_build_timesheet_response(frappe.get_doc(TS_DOCTYPE, n)) for n in names]


@frappe.whitelist()
def create_timesheet(wih_number, product_name=None, start_date=None, end_date=None):
    user = _current_user()

    # Defensive check: the /wih picker already excludes WIHs this user has an
    # open/submitted timesheet for, but this guards against direct API calls
    # bypassing that (the original Express route has no equivalent check).
    existing = frappe.db.get_value(
        TS_DOCTYPE, {"wih_number": wih_number, "user": user, "docstatus": ["in", [0, 1]]}
    )
    if existing:
        frappe.throw(f"You already have an open timesheet ({existing}) for WIH {wih_number}.")

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
    _check_owner(doc)
    return _build_timesheet_response(doc)


@frappe.whitelist()
def update_timesheet(name, product_name=None, start_date=None, end_date=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    _check_owner(doc)
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
    _check_owner(doc)

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
    _check_owner(doc)

    if any(e.get("is_running") for e in doc.timesheet_entry):
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
    })
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def stop_timer(name, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    _check_owner(doc)

    active = next((e for e in doc.timesheet_entry if e.get("is_running")), None)
    if not active:
        frappe.throw("No active timer found on this timesheet.")

    now = now_datetime()
    duration = round(time_diff_in_hours(now, active.start_time), 4)

    active.end_time = now
    active.duration_hours = duration
    active.minutes = round(duration * 60, 2)
    active.is_running = 0
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
    _check_owner(doc)

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
    })
    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


@frappe.whitelist()
def update_entry(name, idx, entry_date=None, start_time=None, end_time=None, duration_hours=None, notes=None):
    doc = frappe.get_doc(TS_DOCTYPE, name)
    _check_owner(doc)

    idx = int(idx)
    row = next((e for e in doc.timesheet_entry if e.idx == idx), None)
    if not row:
        frappe.throw("Entry not found", frappe.DoesNotExistError)

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
    _check_owner(doc)

    idx = int(idx)
    before = len(doc.timesheet_entry)
    doc.timesheet_entry = [e for e in doc.timesheet_entry if e.idx != idx]
    if len(doc.timesheet_entry) == before:
        frappe.throw("Entry not found", frappe.DoesNotExistError)

    _recalc_total_hours(doc)
    doc.save()
    frappe.db.commit()
    return _build_timesheet_response(doc)


# --- Stats -----------------------------------------------------------------

@frappe.whitelist()
def get_timesheet_stats():
    user = _current_user()
    names = frappe.get_all(TS_DOCTYPE, filters={"user": user}, pluck="name", limit_page_length=500)

    total_timesheets = len(names)
    active_timesheets = 0
    submitted_timesheets = 0
    total_hours_today = 0.0
    total_hours_week = 0.0
    has_active_timer = False

    today_str = today()
    week_ago_str = add_days(today_str, -7)

    # Matches the original perf trade-off: full detail (with child entries)
    # is only pulled for the most recent 20 timesheets.
    for n in names[:20]:
        doc = frappe.get_doc(TS_DOCTYPE, n)

        if doc.status == "Draft" and doc.docstatus != 1:
            active_timesheets += 1
        if doc.status == "Submitted" or doc.docstatus == 1:
            submitted_timesheets += 1

        for e in doc.timesheet_entry:
            if e.get("is_running"):
                has_active_timer = True
                continue
            hrs = e.duration_hours or 0
            if str(e.entry_date) == str(today_str):
                total_hours_today += hrs
            if e.entry_date and str(e.entry_date) >= str(week_ago_str):
                total_hours_week += hrs

    return {
        "total_timesheets": total_timesheets,
        "active_timesheets": active_timesheets,
        "submitted_timesheets": submitted_timesheets,
        "total_hours_today": round(total_hours_today, 2),
        "total_hours_week": round(total_hours_week, 2),
        "has_active_timer": has_active_timer,
    }
