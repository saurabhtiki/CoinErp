# Tasks: Phase T2 plan (Repeating tasks and holidays)

Scope: repeating rules, holidays, and the daily job that makes tasks from rules.
No dashboard, calendar, digest email or import yet (T3). T1 (one-time tasks) is done.

Main idea: a **rule** is not a task. A rule has no Due date. It only says how often and on which day.
Example: rule "GSTR1", monthly, due 11th of next month → tasks `GSTR1 - Oct 2026` (due 11 Nov),
`GSTR1 - Nov 2026` (due 11 Dec), and so on.

## 1. Tables (database change, new migration)
- `RecurringTask` (a rule): title, description, owner, reviewer, collaborators, category, priority,
  - `frequency`: daily / weekly / monthly / yearly, and `repeat_every` (1 = every month, 3 = every quarter),
  - `weekday` (weekly), `due_day` 1-31 or "last day" (monthly, yearly), `due_month` (yearly),
  - `due_in_next_period` (work of Oct, due in Nov),
  - `off_day_rule`: previous working day / next working day / keep the date,
  - `create_days_before` (how early the task appears), `start_date`, `end_date` (optional), `is_paused`.
- `RecurringAction`: rule, title, person, days before the due date. Copied as actions on each new task.
- `Holiday`: company, date, name (one per date per company).
- `OffDaySetting`: one per company, which Saturdays are off (1st to 5th). Starts with 2nd and 4th.
  Sunday is always off. A change affects only tasks made after it.
- `Task` gets 3 new fields: `recurring_task` (empty for one-time tasks), `period_label` ("Oct 2026"),
  `period_start` (a date). One rule can have only one task per `period_start`: this stops double creation.

## 2. Date logic (`apps/tasks/schedule.py`, plain functions, no database inside)
- `is_off_day(date, off_saturdays, holidays)`: Sunday, an off Saturday of the company, or a holiday.
- `move_off_day(date, rule, holidays)`: to the previous or next working day, or keep.
- `periods(rule, from_date, count)`: the next periods, each with start, label and due date.
  - Day 31 in a short month → last day of that month (31 → 30 Nov, 28 Feb).
  - Labels: daily `16 Nov 2026`, weekly `Week of 16 Nov 2026`, monthly `Oct 2026`,
    every 3 months `Oct-Dec 2026`, yearly `2026`.
  - Daily rules skip off days (no task on a Sunday).

## 3. Business rules (`services.py`)
- `save_rule` (create / edit), `pause_rule`, `resume_rule`. No delete: pause, or set an end date.
- `preview_dates(rule values)`: next 3 due dates, shown live in the form.
- `create_due_tasks(today)`: for every active rule, make the task of each period whose
  "due date minus create_days_before" has come, if that task does not exist yet.
  - Title = `rule title - period label`. Owner, reviewer, collaborators, category, priority and actions are copied.
  - Created by = the person who made the rule. The owner gets a bell alert (no email, to avoid daily mail).
  - Catch-up: if the job did not run for some days, missed periods are still created (never before `start_date`).
  - A new task is made even if the last one is still open.
- Editing a rule changes only tasks made after the edit. Tasks already made stay as they are.
- A task made by a rule shows read-only "Repeats: Monthly (from rule GSTR1)" with a link to the rule.
- `save_holiday`, `remove_holiday`.

## 4. Who can do what (only through the core access layer)
- Rules: same as tasks. Seen by owner, reviewer, collaborators, creator, the owner's managers, admin.
  Changed or paused by creator, owner, the owner's manager, admin.
- Holidays: everyone with Tasks can see them. Only the admin of the company can add or remove.
- "Create due tasks now" button: admin only.
- One small core helper if needed: "is this user an admin of app X in company Y" (for records that do not exist yet).

## 5. Daily job
- django-q2 schedule, every day at 6:00 am, calls `create_due_tasks`. The schedule is added by a small
  management command `setup_task_jobs` (safe to run again), no new package.
- Errors in one rule are logged and do not stop the other rules.

## 6. Screens
- "Repeating" list (django-datatable): title, owner, repeats ("Monthly, 11th of next month"), next due date,
  status (Active / Paused). Buttons: New rule, Pause / Resume, History.
- Rule side panel (HTMX): the fields change with the frequency (weekly shows weekday, monthly shows day).
  **No Due date field.** Live preview: "First task: Wed 11 Nov 2026, then 11 Dec 2026, 11 Jan 2027".
  Actions section (title, person, days before due). List of the tasks this rule already made.
- "Holidays" list: date, name; add and remove for the admin. On top, five tick boxes for the admin:
  "Saturdays off: 1st, 2nd, 3rd, 4th, 5th".
- Anyone with Tasks can make a rule (confirmed), yearly label is the calendar year.
- Task panel: the "Repeats" line for tasks made by a rule.
- Tooltips on all buttons. Clear error messages.

## 7. Tests (`tests/test_tasks_repeat.py`)
- Dates: monthly "20 of next month", weekly Friday, yearly 30 June, every 3 months, day 31 in February,
  daily skipping Sunday, 2nd-Saturday and holiday moved to previous / next working day.
- Job: creates `create_days_before` days ahead; running twice makes no second task; catch-up after missed days;
  paused and ended rules make nothing; one bad rule does not stop the others.
- Copy: collaborators, reviewer and actions are on the new task; the owner gets a bell.
- Who sees what: rule owner, collaborator, manager, admin, outsider (404), other company (404).
  Only the admin can change holidays and press "Create due tasks now".

## 8. Finish
`uv run pytest`, click through in the browser (make a monthly rule, press "Create due tasks now"),
`/code-review`, commit, set "Current phase" in `apps/tasks/CLAUDE.md`.
