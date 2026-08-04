// ------------------------------------------------------------------
// Thin wrapper around this app's whitelisted methods
// (timesheet_kiosk.api.*). Session is cookie based (sid); CSRF token
// comes back directly in the login() response, so no extra round
// trip or page reload is needed after signing in.
// ------------------------------------------------------------------

const Store = {
  get csrf() { return localStorage.getItem("tk_csrf") || ""; },
  set csrf(v) { localStorage.setItem("tk_csrf", v); },
  get user() { return localStorage.getItem("tk_user") || ""; },
  set user(v) { localStorage.setItem("tk_user", v); },
  clear() { localStorage.removeItem("tk_csrf"); localStorage.removeItem("tk_user"); },
};

async function callMethod(method, args = {}) {
  const res = await fetch(`/api/method/timesheet_kiosk.api.${method}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(Store.csrf ? { "X-Frappe-CSRF-Token": Store.csrf } : {}),
    },
    body: JSON.stringify(args),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const msg = extractMessage(data) || `Request failed (${res.status})`;
    // Only a genuinely stale/invalid session should bounce the user back
    // to the login screen. Other errors (e.g. missing doctype permission,
    // which Frappe also returns as HTTP 403) should surface as-is —
    // clearing the session for those just hides the real problem behind
    // a misleading message and forces a pointless re-login loop.
    if (res.status === 401 || /invalid request|csrf/i.test(msg)) {
      Store.clear();
      throw new Error("Session expired. Please sign in again.");
    }
    throw new Error(msg);
  }
  return data.message;
}

function extractMessage(data) {
  if (!data) return null;
  if (data._server_messages) {
    try {
      const arr = JSON.parse(data._server_messages);
      const msgs = arr
        .map((m) => { try { return JSON.parse(m).message; } catch (e) { return m; } })
        .filter(Boolean);
      if (msgs.length) return msgs.join(" ");
    } catch (e) { /* fall through */ }
  }
  if (typeof data.message === "string") return data.message;
  if (data.exception) {
    const parts = String(data.exception).split(":");
    return parts.length > 1 ? parts.slice(1).join(":").trim() : String(data.exception);
  }
  return null;
}

const API = {
  async login(usr, pwd) {
    // Clear out any pre-existing session cookie first (see reset_session's
    // docstring in api.py) — a GET request, so it's never CSRF-checked,
    // unlike the login POST that follows.
    await fetch("/api/method/timesheet_kiosk.api.reset_session", { credentials: "include" }).catch(() => {});

    const res = await callMethod("login", { usr, pwd });
    Store.user = res.userId;
    Store.csrf = res.csrf_token;
    return res;
  },

  async logout() {
    try { await callMethod("logout"); } catch (e) { /* ignore */ }
    Store.clear();
  },

  isLoggedIn() { return !!Store.user; },

  listWih(search) { return callMethod("list_wih", { search }); },
  getStats() { return callMethod("get_timesheet_stats"); },
  listTimesheets(status, wih_number, page) { return callMethod("list_timesheets", { status, wih_number, page }); },
  createTimesheet(wih_number, start_date, product_name) {
    return callMethod("create_timesheet", { wih_number, start_date, product_name });
  },
  getTimesheet(name) { return callMethod("get_timesheet", { name }); },
  startTimer(name) { return callMethod("start_timer", { name }); },
  stopTimer(name) { return callMethod("stop_timer", { name }); },
  addEntry(name, entry_date, start_time, end_time, notes) {
    return callMethod("add_entry", { name, entry_date, start_time, end_time, notes });
  },
  deleteEntry(name, idx) { return callMethod("delete_entry", { name, idx }); },
  submitTimesheet(name) { return callMethod("submit_timesheet", { name }); },
};
