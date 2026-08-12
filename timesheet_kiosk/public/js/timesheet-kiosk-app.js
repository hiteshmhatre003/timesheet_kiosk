const app = document.getElementById("root");
let timerInterval = null;

// ------------------------------------------------------------------
// Router
// ------------------------------------------------------------------
// Real path-based routing (e.g. /timesheet/login, /timesheet/timer/abc123)
// instead of the old #/login hash routing. The server-side wildcard route
// rule in hooks.py hands back this same app shell for any path under
// /timesheet/, so a hard refresh on a sub-path still works — the browser
// asks the server for e.g. /timesheet/timer/abc123, the server returns
// this page, and currentRoute() below picks the same screen back up from
// window.location.pathname.
const BASE_PATH = "/timesheet";

function currentRoute() {
  let path = location.pathname;
  if (path.startsWith(BASE_PATH)) path = path.slice(BASE_PATH.length);
  return path && path !== "/" ? path : "/dashboard";
}

// Pushes a new entry onto browser history (so Back/Forward work) and
// re-renders. Use { replace: true } for redirects that shouldn't leave a
// Back-button entry (e.g. bouncing an unauthenticated user to /login).
function navigate(route, { replace = false } = {}) {
  const full = BASE_PATH + route;
  if (location.pathname !== full) {
    if (replace) history.replaceState({}, "", full);
    else history.pushState({}, "", full);
  }
  render();
}

// Back/Forward navigation doesn't go through navigate() above, so it needs
// its own listener — this is the path-based router's equivalent of the old
// "hashchange" listener.
window.addEventListener("popstate", render);
window.addEventListener("DOMContentLoaded", () => {
  render();
  registerServiceWorker();
});

function render() {
  clearInterval(timerInterval);
  let route = currentRoute();

  if (!API.isLoggedIn() && route !== "/login") {
    route = "/login";
    history.replaceState({}, "", BASE_PATH + "/login");
  }

  if (route === "/login") return renderLogin();
  if (route === "/dashboard") return renderDashboard();
  if (route === "/new") return renderNewTimesheet();
  if (route.startsWith("/timer/")) return renderTimer(route.split("/timer/")[1]);

  history.replaceState({}, "", BASE_PATH + "/dashboard");
  return renderDashboard();
}

function toast(msg, ms = 2800) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

// ------------------------------------------------------------------
// LOGIN
// ------------------------------------------------------------------
function renderLogin() {
  app.innerHTML = `
    <div class="screen login-wrap">
      <div class="login-header">
        <h1>Timesheet</h1>
        <p>Work In Hand Time Tracker</p>
      </div>
      <div class="login-card">
        <div class="avatar">&#8674;</div>
        <h2>Sign In</h2>
        <p class="sub">Enter your ERPNext credentials</p>
        <div class="login-body">
          <div id="err"></div>
          <div class="field">
            <label>Username</label>
            <input id="usr" type="text" placeholder="your.name@company.com" autocomplete="username" />
          </div>
          <div class="field">
            <label>Password</label>
            <div class="pw-wrap">
              <input id="pwd" type="password" placeholder="••••••••" autocomplete="current-password" />
              <button type="button" id="togglePw">&#128065;</button>
            </div>
          </div>
          <button class="btn btn-primary" id="signInBtn">Sign In</button>
        </div>
      </div>
    </div>
  `;

  document.getElementById("togglePw").onclick = () => {
    const pw = document.getElementById("pwd");
    pw.type = pw.type === "password" ? "text" : "password";
  };

  const doLogin = async () => {
    const usr = document.getElementById("usr").value.trim();
    const pwd = document.getElementById("pwd").value;
    const btn = document.getElementById("signInBtn");
    const errBox = document.getElementById("err");
    errBox.innerHTML = "";
    if (!usr || !pwd) {
      errBox.innerHTML = `<div class="error-box">Please enter username and password</div>`;
      return;
    }
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Signing in...`;
    try {
      await API.login(usr, pwd);
      navigate("/dashboard");
    } catch (e) {
      errBox.innerHTML = `<div class="error-box">${e.message}</div>`;
      btn.disabled = false;
      btn.textContent = "Sign In";
    }
  };

  document.getElementById("signInBtn").onclick = doLogin;
  document.getElementById("pwd").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
}

// ------------------------------------------------------------------
// DASHBOARD
// ------------------------------------------------------------------
let currentFilter = "All";
let dashboardPage = 1;
let dashboardWihSearch = "";
let searchDebounce = null;

async function renderDashboard() {
  app.innerHTML = topbar() + `
    <div class="screen" id="dashScreen">
      <div id="statsArea" class="stat-grid">
        <div class="stat-card"><div class="label">HOURS TODAY</div><div class="value">&hellip;</div></div>
        <div class="stat-card"><div class="label">HOURS WEEK</div><div class="value">&hellip;</div></div>
        <div class="stat-card"><div class="label">ACTIVE SHEETS</div><div class="value">&hellip;</div></div>
        <div class="stat-card"><div class="label">STATUS</div><div class="value">&hellip;</div></div>
      </div>

      <div class="section-head"><h2>My Timesheets</h2></div>
      <div class="tabs">
        ${["All", "Draft", "Submitted"].map(f => `<div class="tab ${f === currentFilter ? "active" : ""}" data-filter="${f}">${f.toUpperCase()}</div>`).join("")}
      </div>
      <div class="field">
        <input id="wihSearchInput" type="text" placeholder="Search by WIH number…" value="${dashboardWihSearch}" />
      </div>
      <div id="sheetListArea"><div class="loading-center">Loading…</div></div>
    </div>
  ` + fab();

  wireTopbar();
  wireFab();
  wireDashboardControls();
  loadStats();
  loadSheetList();
}

async function loadStats() {
  try {
    const stats = await API.getStats();
    const el = document.getElementById("statsArea");
    if (el) el.innerHTML = statCardsHtml(stats);
  } catch (e) {
    // non-fatal — the timesheet list below still loads independently
  }
}

function statCardsHtml(stats) {
  return `
    <div class="stat-card"><div class="label">HOURS TODAY</div><div class="value">${flt2(stats.total_hours_today)}</div></div>
    <div class="stat-card"><div class="label">HOURS WEEK</div><div class="value">${flt2(stats.total_hours_week)}</div></div>
    <div class="stat-card"><div class="label">ACTIVE SHEETS</div><div class="value">${stats.active_timesheets}</div></div>
    <div class="stat-card"><div class="label">${stats.has_active_timer ? "TIMER RUNNING" : "ALL TIMERS STOPPED"}</div><div class="value">${stats.has_active_timer ? "&#9654;" : "&#9632;"}</div></div>
  `;
}

async function loadSheetList() {
  const area = document.getElementById("sheetListArea");
  if (area) area.innerHTML = `<div class="loading-center">Loading…</div>`;
  try {
    const resp = await API.listTimesheets(
      currentFilter === "All" ? undefined : currentFilter,
      dashboardWihSearch || undefined,
      dashboardPage
    );
    if (area) {
      area.innerHTML = sheetListHtml(resp);
      wireSheetList(resp);
    }
  } catch (e) {
    if (area) area.innerHTML = `<div class="error-box">${e.message}</div>`;
  }
}

function sheetListHtml(resp) {
  const sheets = resp.items || [];
  const totalPages = Math.max(1, Math.ceil((resp.total || 0) / (resp.page_size || 10)));
  return `
    <div id="sheetList">
      ${sheets.length ? sheets.map(sheetCard).join("") : `<div class="empty-state">No timesheets found.</div>`}
    </div>
    ${resp.total > resp.page_size ? `
      <div class="pagination">
        <button class="btn btn-outline pagination-btn" id="dashPrevBtn" ${resp.page <= 1 ? "disabled" : ""}>&larr; Prev</button>
        <span class="page-indicator">Page ${resp.page} of ${totalPages}</span>
        <button class="btn btn-outline pagination-btn" id="dashNextBtn" ${resp.page >= totalPages ? "disabled" : ""}>Next &rarr;</button>
      </div>
    ` : ""}
  `;
}

function sheetCard(s) {
  const statusClass = s.status === "Draft" ? "status-draft" : "status-submitted";
  return `
    <div class="sheet-card" data-name="${s.name}">
      <div>
        <div class="wih">${s.wih_number || ""}</div>
        <div class="name">${s.product_name || s.name}</div>
        <div class="meta">${s.start_date || ""} &middot; ${flt2(s.total_hours)} hrs</div>
      </div>
      <div class="right">
        <div class="right-top">
          ${s.is_running_for_me ? `<span class="running-dot" title="Your timer is running"></span>` : ""}
          <span class="status-pill ${statusClass}">${(s.status || "").toUpperCase()}</span>
        </div>
      </div>
    </div>
  `;
}

function flt2(v) { return (v || 0).toFixed(2); }

function wireDashboardControls() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.onclick = () => {
      currentFilter = tab.dataset.filter;
      dashboardPage = 1;
      document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
      loadSheetList();
    };
  });

  const searchInput = document.getElementById("wihSearchInput");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        dashboardWihSearch = searchInput.value.trim();
        dashboardPage = 1;
        loadSheetList();
      }, 350);
    });
  }
}

function wireSheetList(resp) {
  document.querySelectorAll(".sheet-card").forEach(card => {
    card.onclick = () => navigate(`/timer/${card.dataset.name}`);
  });
  const prevBtn = document.getElementById("dashPrevBtn");
  if (prevBtn) prevBtn.onclick = () => { dashboardPage = Math.max(1, dashboardPage - 1); loadSheetList(); };
  const nextBtn = document.getElementById("dashNextBtn");
  if (nextBtn) nextBtn.onclick = () => { dashboardPage += 1; loadSheetList(); };
}

function topbar() {
  return `
    <div class="topbar">
      <div class="brand" id="brandHome">
        <span class="brand-logo">amal</span>
        <span class="brand-title">TIMESHEET</span>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <span class="user-pill" id="userPill">${Store.user}</span>
        <button class="icon-btn" id="logoutBtn">&#8617; Logout</button>
      </div>
    </div>
  `;
}

function wireTopbar() {
  const btn = document.getElementById("logoutBtn");
  if (btn) btn.onclick = async () => { await API.logout(); navigate("/login"); };

  const brand = document.getElementById("brandHome");
  if (brand) brand.onclick = () => navigate("/dashboard");
}

function fab() {
  return `<button class="fab" id="newTimesheetFab">+ New Timesheet</button>`;
}
function wireFab() {
  const btn = document.getElementById("newTimesheetFab");
  if (btn) btn.onclick = () => navigate("/new");
}

// ------------------------------------------------------------------
// NEW TIMESHEET
// ------------------------------------------------------------------
async function renderNewTimesheet() {
  app.innerHTML = topbar() + `<div class="screen" id="newScreen"><div class="loading-center">Loading assigned WIH…</div></div>`;
  wireTopbar();

  let wihList;
  try {
    wihList = await API.listWih();
  } catch (e) {
    document.getElementById("newScreen").innerHTML = `<div class="error-box">${e.message}</div>`;
    return;
  }

  const today = new Date().toISOString().slice(0, 10);
  document.getElementById("newScreen").innerHTML = `
    <button class="back-link" id="backBtn">&larr; Back</button>
    <div class="form-card">
      <div class="form-card-head">
        <h2>New Timesheet</h2>
        <p>Select a Work In Hand order to begin tracking time</p>
      </div>
      <div class="form-card-body">
        <div id="err"></div>
        <div class="field">
          <label>Work In Hand Order</label>
          <select id="wihSelect">
            <option value="">Search WIH order…</option>
            ${wihList.map(w => `<option value="${w.name}">${w.name}</option>`).join("")}
          </select>
        </div>
        ${wihList.length === 0 ? `<p style="color:var(--sub); font-size:12px; margin-top:-8px;">No unassigned WIH orders found — ask your admin to add one via Timesheet Allocation, or check if all your allocated WIH already have an open timesheet.</p>` : ""}
        <div class="two-col">
          <div class="field">
            <label>Start Date</label>
            <input id="startDate" type="date" value="${today}" />
          </div>
          <div class="field">
            <label>Style Code (Optional)</label>
            <input id="styleCode" type="text" placeholder="e.g. Widget A" />
          </div>
        </div>
        <button class="btn btn-primary" id="createBtn" style="margin-top:6px;">Create Timesheet</button>
      </div>
    </div>
  `;

  document.getElementById("backBtn").onclick = () => navigate("/dashboard");
  document.getElementById("createBtn").onclick = async () => {
    const wih = document.getElementById("wihSelect").value;
    const startDate = document.getElementById("startDate").value;
    const style = document.getElementById("styleCode").value;
    const errBox = document.getElementById("err");
    errBox.innerHTML = "";
    if (!wih || !startDate) {
      errBox.innerHTML = `<div class="error-box">Please select a WIH order and start date</div>`;
      return;
    }
    const btn = document.getElementById("createBtn");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Creating...`;
    try {
      const res = await API.createTimesheet(wih, startDate, style);
      navigate(`/timer/${res.name}`);
    } catch (e) {
      errBox.innerHTML = `<div class="error-box">${e.message}</div>`;
      btn.disabled = false;
      btn.textContent = "Create Timesheet";
    }
  };
}

// ------------------------------------------------------------------
// TIMER SCREEN
// ------------------------------------------------------------------
async function renderTimer(name) {
  app.innerHTML = `<div class="screen"><div class="loading-center">Loading timesheet…</div></div>`;
  await loadTimerScreen(name);
}

let entriesPage = 1;
const ENTRIES_PAGE_SIZE = 6;

async function loadTimerScreen(name) {
  // loadTimerScreen is called directly from several button handlers below
  // (start/stop, add manual entry, delete entry) as well as through
  // render(). render() clears timerInterval before calling this, but those
  // direct calls didn't — so every action taken while a timer was running
  // stacked another 1-second ticker on top of the previous one, and they
  // all fought over the same number. Clearing here, unconditionally,
  // guarantees at most one ticker is ever alive no matter which path
  // brought us here.
  clearInterval(timerInterval);
  entriesPage = 1; // always land on the newest entries when a timesheet is (re)loaded

  let doc;
  try {
    doc = await API.getTimesheet(name);
  } catch (e) {
    app.innerHTML = `<div class="screen"><div class="error-box">${e.message}</div></div>`;
    return;
  }

  const sortedEntries = [...doc.timesheet_entry].sort((a, b) => b.idx - a.idx);
  const runningRow = doc.timesheet_entry.find(e => e.is_running);
  const isDraft = doc.status === "Draft" && doc.docstatus !== 1;

  app.innerHTML = `
    <div class="screen">
      <div class="timer-topbar">
        <button class="back-link" id="backBtn" style="margin:0;">&larr; Back</button>
        ${isDraft ? `<button class="btn btn-primary" id="submitBtn" style="width:auto; padding:10px 16px; font-size:12px;">&#10003; Submit Timesheet</button>` : `<span class="status-pill status-submitted">SUBMITTED</span>`}
      </div>

      <div class="wih-card">
        <div class="wih-info-row">
          ${doc.wih_photo ? `<img src="${doc.wih_photo}" class="wih-thumb" id="wihThumb" alt="WIH photo" />` : ""}
          <div>
            <div class="lbl">WORK IN HAND (WIH)</div>
            <div class="wih-name">${doc.wih_number}</div>
            <div class="style">${doc.product_name || ""}</div>
          </div>
        </div>
        <div class="hours-block-group">
          <div class="hours-block">
            <div class="hours-lbl">MY HOURS</div>
            <div class="hours-val" id="personalHours">${flt2(doc.personal_hours)}</div>
          </div>
          <div class="hours-block">
            <div class="hours-lbl">TEAM TOTAL</div>
            <div class="hours-val" id="totalHours">${flt2(doc.total_hours)}</div>
          </div>
        </div>
      </div>

      ${isDraft ? `
        <button class="timer-btn ${runningRow ? "timer-running" : "btn-green"}" id="timerBtn">
          ${runningRow ? "&#9632; Stop Timer" : "&#9654; Start Timer"}
        </button>
      ` : ""}

      <div class="entries-card">
        <div class="entries-head">Time Entries</div>
        <div class="entries-cols"><div>DATE</div><div>START</div><div>END</div><div>HOURS</div><div>MIN</div><div></div></div>
        <div id="entryRows">
          ${renderEntryRows(sortedEntries, isDraft)}
        </div>
        <div id="entriesPagination">${renderEntriesPagination(sortedEntries.length)}</div>
      </div>

      ${isDraft ? `
      <div class="manual-card">
        <div class="manual-head">
          <div class="title" id="manualToggle">+ Add Manual Entry</div>
          <p>Log time that wasn't captured by the timer</p>
        </div>
        <div class="manual-body" id="manualBody" style="display:none;">
          <div class="two-col" style="margin-bottom:14px;">
            <div class="field" style="margin-bottom:0;">
              <label>Date</label>
              <input id="mDate" type="date" value="${new Date().toISOString().slice(0,10)}" />
            </div>
            <div class="field" style="margin-bottom:0;">
              <label>Start Time</label>
              <input id="mStart" type="time" value="08:00" />
            </div>
          </div>
          <div class="two-col" style="margin-bottom:14px;">
            <div class="field" style="margin-bottom:0;">
              <label>End Time</label>
              <input id="mEnd" type="time" value="17:00" />
            </div>
            <div class="field" style="margin-bottom:0;">
              <label>Notes (Optional)</label>
              <input id="mNotes" type="text" placeholder="Why manual?" />
            </div>
          </div>
          <button class="btn btn-outline" id="appendBtn" style="width:auto; padding:12px 18px;">+ Append Record</button>
        </div>
      </div>
      ` : ""}
      <div id="err"></div>
    </div>
  `;

  document.getElementById("backBtn").onclick = () => navigate("/dashboard");

  const wihThumb = document.getElementById("wihThumb");
  if (wihThumb) wihThumb.onclick = () => showImageModal(doc.wih_photo);

  if (isDraft) {
    document.getElementById("timerBtn").onclick = async () => {
      const btn = document.getElementById("timerBtn");
      btn.disabled = true;
      try {
        if (runningRow) {
          await API.stopTimer(name);
        } else {
          await API.startTimer(name);
        }
        await loadTimerScreen(name);
      } catch (e) {
        toast(e.message);
        btn.disabled = false;
      }
    };

    const submitBtn = document.getElementById("submitBtn");
    if (submitBtn) submitBtn.onclick = () => showSubmitModal(name);

    const manualToggle = document.getElementById("manualToggle");
    manualToggle.onclick = () => {
      const body = document.getElementById("manualBody");
      body.style.display = body.style.display === "none" ? "block" : "none";
    };

    document.getElementById("appendBtn").onclick = async () => {
      const mDate = document.getElementById("mDate").value;
      const mStart = document.getElementById("mStart").value;
      const mEnd = document.getElementById("mEnd").value;
      const mNotes = document.getElementById("mNotes").value;
      const errBox = document.getElementById("err");
      errBox.innerHTML = "";
      if (!mDate || !mStart || !mEnd) {
        errBox.innerHTML = `<div class="error-box">Please fill date, start and end time</div>`;
        return;
      }
      try {
        await API.addEntry(name, mDate, mStart, mEnd, mNotes);
        toast("Manual entry added");
        await loadTimerScreen(name);
      } catch (e) {
        errBox.innerHTML = `<div class="error-box">${e.message}</div>`;
      }
    };
  }

  // Wired unconditionally (not just for Draft sheets) so Prev/Next still
  // works when browsing entries on an already-submitted, read-only
  // timesheet. The delete buttons themselves only exist in the DOM when
  // isDraft was true, so this is a no-op for them on submitted sheets.
  wireEntries(name, sortedEntries, isDraft);

  // live-tick the running timer's hours display. doc.timesheet_entry only
  // ever contains the viewing user's OWN entries (the backend filters
  // teammates' rows out), so runningRow here is always this user's own
  // running punch — it ticks against personal_hours, not the shared team
  // total, since we have no live visibility into a teammate's timer.
  if (runningRow) {
    const startMs = new Date(runningRow.start_time.replace(" ", "T")).getTime();
    const baseHours = doc.personal_hours;
    timerInterval = setInterval(() => {
      const hrs = (Date.now() - startMs) / 3600000;
      const el = document.getElementById("personalHours");
      if (el) el.textContent = (parseFloat(baseHours) + hrs).toFixed(2);
    }, 1000);
  }
}

function renderEntryRows(sortedEntries, isDraft) {
  const start = (entriesPage - 1) * ENTRIES_PAGE_SIZE;
  const pageItems = sortedEntries.slice(start, start + ENTRIES_PAGE_SIZE);
  if (!pageItems.length) return `<div class="empty-state">No entries yet</div>`;
  return pageItems.map(entryRow(isDraft)).join("");
}

function renderEntriesPagination(totalCount) {
  if (totalCount <= ENTRIES_PAGE_SIZE) return "";
  const totalPages = Math.max(1, Math.ceil(totalCount / ENTRIES_PAGE_SIZE));
  return `
    <div class="pagination">
      <button class="btn btn-outline pagination-btn" id="entriesPrevBtn" ${entriesPage <= 1 ? "disabled" : ""}>&larr; Prev</button>
      <span class="page-indicator">Page ${entriesPage} of ${totalPages}</span>
      <button class="btn btn-outline pagination-btn" id="entriesNextBtn" ${entriesPage >= totalPages ? "disabled" : ""}>Next &rarr;</button>
    </div>
  `;
}

// Entries are already fully loaded in memory (one get_timesheet call), so
// paging through them is purely a local re-render — no extra API calls.
function wireEntries(name, sortedEntries, isDraft) {
  document.querySelectorAll(".del-entry").forEach(btn => {
    btn.onclick = async () => {
      try {
        await API.deleteEntry(name, btn.dataset.idx);
        await loadTimerScreen(name);
      } catch (e) { toast(e.message); }
    };
  });

  const prevBtn = document.getElementById("entriesPrevBtn");
  if (prevBtn) prevBtn.onclick = () => {
    entriesPage = Math.max(1, entriesPage - 1);
    refreshEntriesDom(name, sortedEntries, isDraft);
  };
  const nextBtn = document.getElementById("entriesNextBtn");
  if (nextBtn) nextBtn.onclick = () => {
    entriesPage += 1;
    refreshEntriesDom(name, sortedEntries, isDraft);
  };
}

function refreshEntriesDom(name, sortedEntries, isDraft) {
  const rowsEl = document.getElementById("entryRows");
  const pagEl = document.getElementById("entriesPagination");
  if (rowsEl) rowsEl.innerHTML = renderEntryRows(sortedEntries, isDraft);
  if (pagEl) pagEl.innerHTML = renderEntriesPagination(sortedEntries.length);
  wireEntries(name, sortedEntries, isDraft);
}

function entryRow(editable) {
  return (e) => `
    <div class="entry-row">
      <div>${e.entry_date || ""}</div>
      <div>${fmtTime(e.start_time)}</div>
      <div>${e.is_running ? `<span class="running-badge">running</span>` : fmtTime(e.end_time)}</div>
      <div>${flt2(e.duration_hours)}</div>
      <div>${e.minutes ? Math.round(e.minutes) : 0}</div>
      <div>${editable && !e.is_running ? `<button class="del del-entry" data-idx="${e.idx}">&#128465;</button>` : ""}</div>
    </div>
  `;
}

function fmtTime(dt) {
  if (!dt) return "";
  const d = new Date(dt.replace(" ", "T"));
  if (isNaN(d)) return dt;
  return d.toTimeString().slice(0, 5);
}

function showImageModal(url) {
  if (!url) return;
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  wrap.innerHTML = `
    <div class="image-modal">
      <button class="image-modal-close" id="imgModalClose" aria-label="Close">&times;</button>
      <img src="${url}" alt="WIH photo" />
    </div>
  `;
  // Tap the dark backdrop (not the image itself) to close.
  wrap.onclick = (e) => { if (e.target === wrap) wrap.remove(); };
  document.body.appendChild(wrap);
  document.getElementById("imgModalClose").onclick = () => wrap.remove();
}

function showSubmitModal(name) {
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  wrap.innerHTML = `
    <div class="modal">
      <h3>Submit Timesheet?</h3>
      <p>This will <strong>lock</strong> the timesheet and submit it to ERPNext. Once submitted, no further changes can be made. Make sure all your time entries are accurate before proceeding.</p>
      <div class="row">
        <button class="btn btn-outline" id="cancelSubmit">Cancel</button>
        <button class="btn btn-primary" id="confirmSubmit">Yes, Submit &amp; Lock</button>
      </div>
    </div>
  `;
  document.body.appendChild(wrap);
  document.getElementById("cancelSubmit").onclick = () => wrap.remove();
  document.getElementById("confirmSubmit").onclick = async () => {
    const btn = document.getElementById("confirmSubmit");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>`;
    try {
      await API.submitTimesheet(name);
      wrap.remove();
      toast("Timesheet submitted");
      navigate("/dashboard");
    } catch (e) {
      toast(e.message);
      wrap.remove();
    }
  };
}

// ------------------------------------------------------------------
// PWA service worker
// ------------------------------------------------------------------
function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/timesheet-sw.js", { scope: "/timesheet" }).catch(() => {});
  }
}
