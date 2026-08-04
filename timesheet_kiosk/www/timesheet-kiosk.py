import frappe
from frappe.utils import now_datetime

no_cache = 1


def get_context(context):
    """
    Injects the current session's CSRF token so the SPA (loaded below via
    timesheet-kiosk.html) can attach it to every state-changing API call.
    Frappe requires this header on POST/PUT/DELETE for logged-in sessions.

    Also injects asset_version: a value that changes on every page load,
    appended as a "?v=..." query string to our own JS/CSS/manifest URLs in
    the HTML below. This exists because of a real caching bug that cost a
    lot of confused debugging: this page itself has no_cache = 1, but the
    *static asset files* it links to (under /assets/timesheet_kiosk/...)
    are served by Frappe's static file handler, which sets its own
    long-lived Cache-Control headers independent of this page. A browser's
    HTTP cache can keep serving an old timesheet-kiosk-app.js by that exact
    filename for a long time even after a fresh deploy — the earlier fix to
    the service worker's caching strategy did not touch this at all, since
    it's the browser's HTTP cache underneath the service worker, not the
    service worker's own cache. Changing the query string forces the
    browser to treat it as a new URL and fetch fresh bytes every time.
    """
    context.csrf_token = frappe.sessions.get_csrf_token()
    context.asset_version = now_datetime().strftime("%Y%m%d%H%M%S")
    return context
