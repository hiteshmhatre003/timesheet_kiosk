app_name = "timesheet_kiosk"
app_title = "Timesheet Kiosk"
app_publisher = "Amal Embroideries Private Limited"
app_description = "Tablet-friendly shop floor timesheet with start/stop timer, built on Employee Timesheet."
app_email = "admin@example.com"
app_license = "MIT"

# Serves the built React frontend at /timesheet-kiosk
# (and any sub-path, so client-side routing inside the SPA keeps working
# even on a hard refresh, e.g. /timesheet-kiosk/timesheets/WIH-0001)
website_route_rules = [
    {"from_route": "/timesheet-kiosk", "to_route": "timesheet-kiosk"},
    {"from_route": "/timesheet-kiosk/<path:app_path>", "to_route": "timesheet-kiosk"},
]
