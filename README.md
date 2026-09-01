# Purchase Mobile

A standalone Frappe app: the Purchase Entry DocType, its automation
(region → warehouse routing, zero-valuation stock receipt), a
whitelisted API, and a React/Vite mobile web app - all in one
installable package, like `timesheet_kiosk`. Install it on any site
that has the three EUR warehouses set up and it works.

## What's in here

```
pyproject.toml                                    makes this a valid, installable Frappe app
purchase_mobile/
  hooks.py, __init__.py, modules.txt              app scaffolding
  api.py                                           whitelisted endpoints the mobile app calls
  www/purchase-app/                                the already-built frontend (served at /purchase-app)
  purchase_mobile/doctype/purchase_entry/          the Purchase Entry DocType + controller
mobile/                                            the React/Vite source, if you want to change the UI later
```

This matches the same layout as your working `timesheet_kiosk` app:
`purchase_mobile/hooks.py` at one level, with the doctype's own module
folder (which happens to share the app's name) one level deeper still,
holding the DocType files.

## 0. Upload this correctly - don't drag the outer folder

If you're using GitHub's web upload instead of git: open this folder,
select **everything inside it** (`pyproject.toml`, `README.md`,
`purchase_mobile/`, `mobile/`, etc.), and drag *those selected items*
into GitHub's upload box - not the outer folder itself. Dragging the
folder adds an extra wrapping layer and reproduces the exact
"hooks.py not found" error you saw before.

## 1. If Purchase Entry already exists in Amal, remove it first

DocType names are unique per site, so you can't have "Purchase Entry"
defined in both Amal and this app at the same time. On uatamal:

- If you haven't pushed the earlier `purchase_entry.py` changes to
  Amal, there's nothing to undo - skip this.
- If Amal already has a "Purchase Entry" DocType (from your original
  screenshots) and you want this app to own it going forward: back up
  or note down any test records, then delete the DocType from Amal
  (DocType list → Purchase Entry → Delete), or rename it if you'd
  rather keep the old one around for reference.

## 2. Push this repo to GitHub

```bash
git init
git add .
git commit -m "Purchase mobile app"
git branch -M main
git remote add origin <your new repo URL>
git push -u origin main
```

## 3. Add it on Frappe Cloud

Dashboard → your bench → Apps → Add App → GitHub → paste the repo URL,
branch `main`. Click Add App, then deploy the bench.

## 4. Install it on the site

Sites → uatamal.frappe.cloud → Apps → Install App → Purchase Mobile.
This installs the DocType, the API, and the mobile app together in one
step - nothing else to wire up.

## 5. Set up access and test

Create a "Purchase Entry User" role with Create + Submit + Read on
Purchase Entry only, assign it to whoever will use the app. Then open
`https://uatamal.frappe.cloud/purchase-app` on a phone, log in, and
submit one test purchase. Check that the Stock Entry lands in the
right warehouse at a zero rate, and that the item shows up with its
photo on the Stock tab.

## Reusing this on another site later

Install the same app there (Add App with this repo's URL, then Install
App on that site) - as long as the site has warehouses matching the
names in `REGION_WAREHOUSE_MAP` inside
`purchase_mobile/purchase_mobile/doctype/purchase_entry/purchase_entry.py`,
it works immediately. Edit that map first if the new site uses
different warehouse names.

## Changing the UI later

```bash
cd mobile
npm install
npm run build
```

This rebuilds straight into `purchase_mobile/www/purchase-app`. Commit
the result and push - same deploy flow as above.
