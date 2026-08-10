app_name = "timesheet_kiosk"
app_title = "Timesheet Kiosk"
app_publisher = "Amal Embroideries Private Limited"
app_description = "Tablet-friendly shop floor timesheet with start/stop timer, built on Employee Timesheet."
app_email = "admin@example.com"
app_license = "MIT"

# Serves the plain HTML/CSS/JS frontend at /timesheet (and any sub-path, so
# the SPA's own path-based router keeps working even on a hard refresh,
# e.g. /timesheet/timer/WIH-0001 — the browser asks the server for that
# exact path, and this wildcard rule makes sure the server still hands back
# the same app shell instead of a 404, letting the frontend JS take over
# routing from there).
website_route_rules = [
    {"from_route": "/timesheet", "to_route": "timesheet"},
    {"from_route": "/timesheet/<path:app_path>", "to_route": "timesheet"},
]

# The app used to live at /timesheet-kiosk. Some phones still have that URL
# saved as a home-screen PWA icon, so redirect it (and any sub-path under
# it) to the new /timesheet instead of letting it 404.
website_redirects = [
    {"source": r"/timesheet-kiosk(.*)", "target": r"/timesheet\1"},
]
