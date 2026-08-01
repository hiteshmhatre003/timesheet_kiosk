const app = document.getElementById("root");
let timerInterval = null;

// ------------------------------------------------------------------
// Router
// ------------------------------------------------------------------
function navigate(hash) { window.location.hash = hash; }

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", () => {
  if (!API.isLoggedIn() && !location.hash.startsWith("#/login")) {
    navigate("#/login");
  }
  render();
  registerServiceWorker();
});

function render() {
  clearInterval(timerInterval);
  const hash = location.hash || "#/login";

  if (!API.isLoggedIn() && hash !== "#/login") {
    navigate("#/login");
    return;
  }

  if (hash === "#/login") return renderLogin();
  if (hash === "#/dashboard" || hash === "#/") return renderDashboard();
  if (hash === "#/new") return renderNewTimesheet();
  if (hash.startsWith("#/timer/")) return renderTimer(hash.split("#/timer/")[1]);

  navigate("#/dashboard");
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
      navigate("#/dashboard");
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

async function renderDashboard() {
  app.innerHTML = topbar() + `<div class="screen" id="dashScreen"><div class="loading-center">Loading…</div></div>` + fab();
  wireTopbar();
  wireFab();

  try {
    const [stats, sheets] = await Promise.all([
      API.getStats(),
      API.listTimesheets(currentFilter === "All" ? undefined : currentFilter),
    ]);
    document.getElementById("dashScreen").innerHTML = dashboardBody(stats, sheets);
    wireDashboardBody();
  } catch (e) {
    document.getElementById("dashScreen").innerHTML = `<div class="error-box">${e.message}</div>`;
  }
}

function dashboardBody(stats, sheets) {
  return `
    <div class="stat-grid">
      <div class="stat-card"><div class="label">HOURS TODAY</div><div class="value">${flt2(stats.total_hours_today)}</div></div>
      <div class="stat-card"><div class="label">HOURS WEEK</div><div class="value">${flt2(stats.total_hours_week)}</div></div>
      <div class="stat-card"><div class="label">ACTIVE SHEETS</div><div class="value">${stats.active_timesheets}</div></div>
      <div class="stat-card"><div class="label">${stats.has_active_timer ? "TIMER RUNNING" : "ALL TIMERS STOPPED"}</div><div class="value">${stats.has_active_timer ? "&#9679;" : "&#9675;"}</div></div>
    </div>

    <div class="section-head"><h2>My Timesheets</h2></div>
    <div class="tabs">
      ${["All", "Draft", "Submitted"].map(f => `<div class="tab ${f === currentFilter ? "active" : ""}" data-filter="${f}">${f.toUpperCase()}</div>`).join("")}
    </div>
    <div id="sheetList">
      ${sheets.length ? sheets.map(sheetCard).join("") : `<div class="empty-state">No timesheets yet. Tap "New Timesheet" to start.</div>`}
    </div>
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
        <span class="status-pill ${statusClass}">${(s.status || "").toUpperCase()}</span>
      </div>
    </div>
  `;
}

function flt2(v) { return (v || 0).toFixed(2); }

function wireDashboardBody() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.onclick = () => { currentFilter = tab.dataset.filter; renderDashboard(); };
  });
  document.querySelectorAll(".sheet-card").forEach(card => {
    card.onclick = () => navigate(`#/timer/${card.dataset.name}`);
  });
}

function topbar() {
  return `
    <div class="topbar">
      <div class="brand">
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
  if (btn) btn.onclick = async () => { await API.logout(); navigate("#/login"); };
}

function fab() {
  return `<button class="fab" id="newTimesheetFab">+ New Timesheet</button>`;
}
function wireFab() {
  const btn = document.getElementById("newTimesheetFab");
  if (btn) btn.onclick = () => navigate("#/new");
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

  document.getElementById("backBtn").onclick = () => navigate("#/dashboard");
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
      navigate(`#/timer/${res.name}`);
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

async function loadTimerScreen(name) {
  let doc;
  try {
    doc = await API.getTimesheet(name);
  } catch (e) {
    app.innerHTML = `<div class="screen"><div class="error-box">${e.message}</div></div>`;
    return;
  }

  const runningRow = doc.timesheet_entry.find(e => e.is_running);
  const isDraft = doc.status === "Draft" && doc.docstatus !== 1;

  app.innerHTML = `
    <div class="screen">
      <div class="timer-topbar">
        <button class="back-link" id="backBtn" style="margin:0;">&larr; Back</button>
        ${isDraft ? `<button class="btn btn-primary" id="submitBtn" style="width:auto; padding:10px 16px; font-size:12px;">&#10003; Submit Timesheet</button>` : `<span class="status-pill status-submitted">SUBMITTED</span>`}
      </div>

      <div class="wih-card">
        <div>
          <div class="lbl">WORK IN HAND (WIH)</div>
          <div class="wih-name">${doc.wih_number}</div>
          <div class="style">${doc.product_name || ""}</div>
        </div>
        <div>
          <div class="hours-lbl">TOTAL ACCUMULATED HOURS</div>
          <div class="hours-val" id="totalHours">${flt2(doc.total_hours)}</div>
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
          ${doc.timesheet_entry.length ? doc.timesheet_entry.map(entryRow(isDraft)).join("") : `<div class="empty-state">No entries yet</div>`}
        </div>
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

  document.getElementById("backBtn").onclick = () => navigate("#/dashboard");

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

    document.querySelectorAll(".del-entry").forEach(btn => {
      btn.onclick = async () => {
        try {
          await API.deleteEntry(name, btn.dataset.idx);
          await loadTimerScreen(name);
        } catch (e) { toast(e.message); }
      };
    });
  }

  // live-tick the running timer's hours display
  if (runningRow) {
    const startMs = new Date(runningRow.start_time.replace(" ", "T")).getTime();
    const baseHours = doc.total_hours;
    timerInterval = setInterval(() => {
      const hrs = (Date.now() - startMs) / 3600000;
      const el = document.getElementById("totalHours");
      if (el) el.textContent = (parseFloat(baseHours) + hrs).toFixed(2);
    }, 1000);
  }
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
      navigate("#/dashboard");
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
    navigator.serviceWorker.register("/timesheet-kiosk-sw.js", { scope: "/timesheet-kiosk" }).catch(() => {});
  }
}
