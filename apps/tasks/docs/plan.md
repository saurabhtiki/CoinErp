# Tasks: Phase T3 plan (Dashboard, Calendar, Daily email, Import)

Status (2026-11-17): Parts A, B, C done and committed. Part D (import) skipped for now, by your choice;
build it later when the CSV files from the old Sheet are ready.

## Context
T1 (one-time tasks) and T2 (repeating rules, holidays) are done. T3 finishes the Tasks app scope in
`apps/tasks/docs/project.md`: a Dashboard, a Calendar, the daily morning email, and the one-time import from
the old Google Sheet. This plan replaces `apps/tasks/docs/plan.md` (T2) when building starts.

Work in 4 parts. Each part = code + tests + commit, then I stop for your OK.
Everything counts only tasks the person may see: `visible_tasks(user)` in `apps/tasks/services.py`
(core access layer underneath). No new permission checks inside the app.

## Part A. Dashboard
- New page "Dashboard" (menu item, first in Tasks). Logic in `services.py` (`dashboard_numbers(user, today)`),
  view only renders.
- **Count cards**: Overdue, Due today, Due this week, Waiting for my review, Blocked.
  Click a card → task list with that filter (reuse `TaskListView` with a filter value in the URL).
- **Per-person table** (django-datatable): one row per person whose tasks I can see:
  open, overdue, done this month, on-time %. A plain member sees only their own row.
- **On-time %** = tasks completed this month with `completed_at` date ≤ `due_date`, out of all completed this month.
  No completed tasks → "–" (not 0%).
- **Charts** (Chart.js, one local file `static/vendor/chart.umd.min.js`, loaded only on this page):
  open tasks by status (bar), open tasks by category (bar). Data passed with `json_script`, no API.
- Tooltips on cards and table headers ("Overdue: due date has passed and not completed").
- No database change.

## Part B. Calendar
- Month grid built with DaisyUI/Tailwind (no library). Prev / Next / Today buttons via HTMX (swap the grid only).
- Each day shows its tasks (code + short title, colour by status; overdue in red). Many tasks → "+3 more".
- Off days shaded: Sundays, the company's off Saturdays, holidays (holiday name shown). Reuse `is_off_day`
  in `apps/tasks/schedule.py` and the `Holiday` / `OffDaySetting` tables.
- Switch: **Mine** (owner / reviewer / action on it, i.e. `my_tasks`) or **All I can see** (`visible_tasks`).
- Click a task → opens the existing task side panel (`tasks:detail`).
- No drag-and-drop (due-date change needs a comment; done from the side panel as today).

## Part C. Daily morning email
- `send_daily_digest(today)` in `services.py`: one email per person with three lists:
  **Due today**, **Overdue**, **Waiting for my review**. Each line links to the task.
- Sent only if the list is not empty, and only on a working day (skip Sunday, off Saturday, holiday of the
  person's company; if the person is in several companies, skip only if it is an off day in all of them).
- Sent with core `notify(..., channels=email only)` (`core/notifications/services.py`), so the sandbox writes it to
  the Sent mail screen instead of sending.
- Schedule: django-q2 daily at 7:00 am, added to the existing `setup_task_jobs` command (safe to run again).
- One person's error is logged and does not stop the others.

## Part D. Import from the old Sheet (SKIPPED for now: build when the CSV files are shared)
- Management command `import_old_tasks <rules.csv> <tasks.csv> --company <code> [--commit]`.
  Default is **dry run**: reads everything, lists every error by row ("Row 14: owner 'amar@x' not found"),
  saves nothing. With `--commit`: all or nothing (one transaction).
- Imports: repeating rules (as `RecurringTask` + actions) and **open** tasks only. Completed tasks stay in the Sheet.
- People matched by email; categories created if missing (listed in the dry-run output).
- Column mapping written after I see your files; the plan for D is confirmed again then.
- Imported tasks get a system note "Imported from the old Sheet".

## Tests (`tests/test_tasks_dashboard.py`, `test_tasks_calendar.py`, `test_tasks_digest.py`, `test_tasks_import.py`)
- Dashboard: card counts right; manager sees team rows, member sees only own row, other company's tasks never
  counted; on-time % (on time, late, none done → "–"); card links open the right filtered list.
- Calendar: tasks on the right day; holidays and off Saturdays shaded; Mine vs All; outsider sees nothing.
- Digest: right three lists; nothing to send → no email; Sunday / holiday → no email; one bad user does not stop
  others; running the setup command twice makes one schedule.
- Import: dry run saves nothing and lists errors; `--commit` with one bad row saves nothing; good file imports
  rules, actions and open tasks; completed rows skipped.

## Packages / database
- No Python package. One JS file (Chart.js) added to `static/vendor` — I'll tell you the exact file and version
  before downloading it.
- No database change planned.

## Decisions (agreed 2026-11-17)
1. Dashboard: count cards, per-person table, simple charts, on-time %.
2. Charts: Chart.js as a local file.
3. On-time = completed on or before the (current) due date.
4. Calendar: hand-built month grid, tasks only, Mine / All switch.
5. Daily email: 7:00 am, working days only, only if there is something to show, email only.
6. Import: management command with dry run; you will share the CSV files.
7. 4 parts, stop for OK after each.

## Finish
`uv run pytest`, click through in the browser (dashboard, calendar, run the digest in sandbox and see it in
Sent mail, dry-run import), `/code-review`, commit, set "Current phase" in `apps/tasks/CLAUDE.md`
and the root `CLAUDE.md`.
