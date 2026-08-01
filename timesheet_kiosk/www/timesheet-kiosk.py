import frappe

no_cache = 1


def get_context(context):
    """
    Injects the current session's CSRF token so the SPA (loaded below via
    timesheet-kiosk.html) can attach it to every state-changing API call.
    Frappe requires this header on POST/PUT/DELETE for logged-in sessions.
    """
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
