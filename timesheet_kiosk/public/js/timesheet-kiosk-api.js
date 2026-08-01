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

  if (res.status === 403) {
    Store.clear();
    throw new Error("Session expired. Please sign in again.");
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = (data && (data._server_messages || data.exc || data.message)) || `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? stripServerMessage(msg) : "Something went wrong");
  }
  return data.message;
}

function stripServerMessage(msg) {
  // frappe.throw() messages sometimes arrive as a JSON-encoded array string
  try {
    const parsed = JSON.parse(msg);
    if (Array.isArray(parsed) && parsed[0]) {
      const inner = JSON.parse(parsed[0]);
      return inner.message || msg;
    }
  } catch (e) { /* not JSON, use as-is */ }
  return msg;
}

const API = {
  async login(usr, pwd) {
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
  listTimesheets(status) { return callMethod("list_timesheets", { status }); },
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
