# Timesheet Kiosk

Tablet-friendly shop floor timesheet with a start/stop timer, built on top
of a custom `Employee Timesheet` doctype in ERPNext.

This is a Frappe custom app. **Everything in this folder (the one this
README is in) is the repo root** — there is no extra wrapping folder.

```
./                      ← repo root — this is what goes on GitHub
├── license.txt
├── pyproject.toml
├── requirements.txt
├── DOCTYPE_REQUIREMENTS.md
└── timesheet_kiosk/     ← the actual app module (contains hooks.py)
    ├── __init__.py
    ├── hooks.py
    ├── modules.txt
    ├── api.py
    ├── config/
    └── www/
```

## Getting this onto GitHub (do this exactly)

**Option A — git (recommended, most reliable):**

```bash
cd timesheet_kiosk        # the folder this README is in
git init                  # skip if already a git repo
git add .
git commit -m "Timesheet Kiosk Frappe app"
git branch -M main
git remote add origin https://github.com/<your-username>/timesheet_kiosk.git
git push -u origin main
```

If Replit has a shell with internet + git available, run these there —
it avoids the browser drag-and-drop step entirely.

**Option B — GitHub web upload (no git/terminal):**

1. Create a new, empty repo on GitHub (do **not** initialize with a README).
2. On the empty repo's page, click **"uploading an existing file."**
3. Open this folder on your computer, select **everything inside it**
   (`license.txt`, `pyproject.toml`, `timesheet_kiosk/`, etc. — select
   all of them, e.g. Ctrl+A / Cmd+A while inside the folder).
4. Drag those *selected items* into the upload box.

   ⚠️ **Do not drag the folder itself.** If you drag the outer folder,
   GitHub nests everything one level deeper than it should be
   (`repo/timesheet_kiosk/hooks.py` becomes
   `repo/timesheet_kiosk/timesheet_kiosk/hooks.py`), which is exactly
   what causes Frappe Cloud's "hooks.py or patches.txt not found" error.
5. Commit directly to `main`.

## Connect it to Frappe Cloud

1. Frappe Cloud dashboard → your bench → **Apps** → **Add App** →
   **Add from GitHub** → authorize access → select the repo/branch.
2. Trigger a new deploy on the bench.
3. Once deployed: **Sites → your site → Install App** → select
   `timesheet_kiosk`.
4. Test the backend: visit
   `https://yoursite.frappe.cloud/api/method/timesheet_kiosk.api.healthz`
   while logged into that site. You should see `{"message": {"status": "ok"}}`.

## Before installing

Open `DOCTYPE_REQUIREMENTS.md` and compare it against what actually
exists in your ERPNext instance today (Customize Form / DocType List).
Fix any mismatches — especially the `Timesheet Allocation` doctype,
which likely doesn't exist yet.

## Frontend

The frontend is plain HTML/CSS/JS — **no build step, no Node, no `pnpm
build`.** The old plan to port the Replit React app has been dropped in
favor of hand-written vanilla JS that talks to the same `api.py` endpoints,
since it's easier for a non-developer to maintain (edit a `.js`/`.css` file
directly, commit, deploy — nothing to compile).

Files:

```
timesheet_kiosk/
├── public/
│   ├── css/timesheet-kiosk.css
│   ├── js/timesheet-kiosk-api.js      ← talks to api.py
│   ├── js/timesheet-kiosk-app.js      ← screens + routing
│   ├── images/icon-192.png, icon-512.png
│   └── timesheet-kiosk-manifest.json  ← makes it installable on a phone
└── www/
    ├── timesheet-kiosk.html           ← shell that loads the above
    ├── timesheet-kiosk.py             ← injects CSRF token
    └── timesheet-kiosk-sw.js          ← offline app-shell caching
```

Nothing else to paste in. Push, deploy, done.

## Known behavior changes from the Node version

- **Login no longer requires an Employee record** — any valid ERPNext
  user can log in and get their own timesheets. Restrict via ERPNext
  roles/permissions if needed, not this app.
- **WIH uniqueness is scoped per-user, not global** — two different
  employees could each get their own Employee Timesheet against the
  same WIH number. If you want one timesheet per WIH *globally*, that
  needs an extra check added to `create_timesheet()` in `api.py`.

### License

MIT
