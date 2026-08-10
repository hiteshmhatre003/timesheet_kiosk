import os

import frappe
from frappe.utils import now_datetime

no_cache = 1


def _asset_version():
    """A version string that changes only when the app's own files change
    (i.e. on deploy) — NOT on every single page load like the previous
    now_datetime()-based version did.

    The previous version fixed a real staleness bug (a browser could keep
    serving an old cached JS file after a deploy) but at a real cost: since
    the "?v=..." query string was different on every single request, the
    browser could never reuse its own cache between visits, even when
    nothing had changed since the last one. That meant re-downloading the
    full CSS/JS/manifest payload on every page load, every time — directly
    working against the app feeling fast to open.

    Using the on-disk modification time of the app's own files gives the
    same anti-staleness guarantee (it changes exactly when a deploy touches
    one of these files) while letting the browser cache normally in
    between deploys, which is what Frappe's long-lived Cache-Control
    headers on /assets/... were already set up for but couldn't actually
    take advantage of before.
    """
    app_path = frappe.get_app_path("timesheet_kiosk")
    candidates = [
        os.path.join(app_path, "public", "js", "timesheet-kiosk-app.js"),
        os.path.join(app_path, "public", "js", "timesheet-kiosk-api.js"),
        os.path.join(app_path, "public", "css", "timesheet-kiosk.css"),
        os.path.join(app_path, "www", "timesheet.html"),
    ]
    mtimes = [os.path.getmtime(p) for p in candidates if os.path.exists(p)]
    if not mtimes:
        # Fallback to the old always-changing behaviour rather than crash
        # the page if, for some reason, none of the expected files exist.
        return now_datetime().strftime("%Y%m%d%H%M%S")
    return str(int(max(mtimes)))


def get_context(context):
    """
    Injects the current session's CSRF token so the SPA (loaded below via
    timesheet.html) can attach it to every state-changing API call.
    Frappe requires this header on POST/PUT/DELETE for logged-in sessions.

    Also injects asset_version (see _asset_version above): appended as a
    "?v=..." query string to our own JS/CSS/manifest URLs in the HTML
    below, so a browser can never keep serving stale JS/CSS after a new
    version has been deployed, without also defeating caching in between
    deploys.

    This page (and its file) used to be named "timesheet-kiosk"; it's now
    served at /timesheet instead of /timesheet-kiosk (see hooks.py's
    website_route_rules and website_redirects). Nothing else about how this
    file works changed.
    """
    context.csrf_token = frappe.sessions.get_csrf_token()
    context.asset_version = _asset_version()
    return context
