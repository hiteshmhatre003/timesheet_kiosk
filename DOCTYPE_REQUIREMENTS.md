# Doctype fields required by this app

Check these against your live ERPNext instance via **Customize Form** (for
existing doctypes) or **New DocType** (for the new one). Everything below
can be done in the browser — no code required.

## 1. Employee Timesheet (parent, must be "Is Submittable")

| Field name       | Type        | Notes                                              |
|-------------------|-------------|-----------------------------------------------------|
| `wih_number`      | Data/Link   | Mandatory                                           |
| `user`            | Link (User) | **Mandatory — replaces the old `employee` field.**  |
| `product_name`    | Data        | Optional                                            |
| `start_date`      | Date        | Set automatically on creation                       |
| `end_date`        | Date        | Optional                                            |
| `status`          | Select      | Options: `Draft`, `Submitted`                       |
| `total_hours`     | Float       | Optional — not auto-calculated by this API           |
| `notes`           | Small Text  | Optional                                            |
| `timesheet_entry` | Table       | Child table → **Timesheet Entry** (see below)       |

Under **DocType → Employee Timesheet → Settings**, confirm **"Is
Submittable"** is checked — this is what makes `submit_timesheet()` lock
the record from further edits.

If your existing doctype still has the old `employee` field (Link to
Employee) from an earlier version of this project, you can leave it in
place unused, or remove it — the API no longer reads or writes it.

## 2. Timesheet Entry (child table)

| Field name         | Type     | Notes                                                        |
|---------------------|----------|----------------------------------------------------------------|
| `entry_date`        | Date     |                                                                  |
| `start_time`        | **Datetime** | **Important: use Datetime, not Time** — the app stores full `YYYY-MM-DD HH:MM:SS` values, not bare time-of-day, so entries correctly track which calendar day they belong to. |
| `end_time`          | **Datetime** | Same as above.                                             |
| `duration_hours`    | Float    |                                                                  |
| `minutes`           | Float    | **Field name is `minutes`, not `duration_minutes`** — confirmed against the live doctype. `api.py` writes to this exact fieldname. |
| `notes`             | Text     |                                                                |
| `is_running`        | Check    | `1` while a timer is actively running on this row, `0` once stopped. This is how the app knows whether a timesheet has an active timer — not by checking whether `end_time` is blank. |

## 3. Timesheet Allocation (new parent doctype)

This doctype doesn't appear to exist yet in earlier conversations — it's
new in this version of the app. A supervisor/admin creates one of these
per user to control which WIH numbers that user is allowed to log time
against.

| Field name | Type        | Notes                                    |
|-------------|-------------|-------------------------------------------|
| `user`      | Link (User) | Mandatory                                 |
| `wih`       | Table       | Child table → **Timesheet Allocation WIH** (see below) — **field name must literally be `wih`**, the API reads this exact fieldname. |

## 4. Timesheet Allocation WIH (new child table)

| Field name | Type                  | Notes                                    |
|-------------|------------------------|---------------------------------------------|
| `wih`       | Link (Work In Hand)   | Mandatory — **field name must literally be `wih`**. |

---

### Quick way to check what already exists

Search **DocType List** in your ERPNext instance and look for `Employee
Timesheet`, `Timesheet Entry`, `Timesheet Allocation`, and `Timesheet
Allocation WIH`. Open each and compare its **Fields** tab against the
tables above before installing this app.
