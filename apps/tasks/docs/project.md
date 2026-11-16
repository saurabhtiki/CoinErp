# Tasks app: scope and requirements

Replaces the Google Apps Script "Task Manager" (data in a Google Sheet). First plug-in app of CoinERP.
Uses only the shared `core` (access, files, audit, notifications). No own permission checks.

## What a task has
- Number (`TSK-0051`), title, description, owner, due date, category, priority (High / Medium / Low).
- Status: Not Started, In Progress, Blocked, Under Review, Completed.
- Reviewer (optional): with a reviewer, "Done" first goes to Under Review; the reviewer completes it.
- Collaborators: can view, comment and add files.
- Actions: small sub-steps, each with a person, a date and a done tick. Example: "Send data to CA, Amar, 18 Nov".
- Files: real uploads (core files, 10 MB; PDF, JPG, PNG, Excel, Word, CSV) and links (for example a Drive link).
- Comments. The app also adds its own notes, for example "Due date moved 20 Nov → 25 Nov".

## Rules
- A comment is required when the due date is changed or the task is set to Blocked.
- Each due-date change adds 1 to a counter shown on the task ("moved 3 times").
- One-click Done from the list.

## Repeating tasks (changed from the old app)
A task and a repeating rule are two separate things.
- One-time task: has a Due date, no repeat fields.
- Repeating rule: no Due date, only the rule (daily / weekly / monthly / yearly, every N, due day,
  same or next period, off-day handling, create N days before due). The form previews the next dates.
- Tasks are created from rules by a daily job. Title gets the period: `GSTR1 - Oct 2026`.
- Collaborators, reviewer and actions are copied to every created task.
- Off days: Sundays, 2nd and 4th Saturdays, and the Holiday list.

## Who sees what (through the core access layer)
- A member sees tasks where they are owner, creator, reviewer, collaborator or have an action.
- A manager also sees tasks owned by people who report to them (all levels, `Employee.reports_to`).
- An admin (role without "own records only") sees all tasks of the company.
- Nobody sees another company's tasks.

## Screens
My tasks, Assigned by me, All tasks, task side panel (details, actions, files, comments),
Recurring rules, Holidays, Dashboard, Calendar.

## Alerts
- Bell + email: task assigned, comment added, sent for review.
- Daily morning email: due today, overdue, waiting for my review.

## Not included
Drive folder creation, "Export to Sheet" (CSV export instead), Source filter, a People screen
(people, departments and managers come from core).

## Old data
One-time import of recurring rules and open tasks from the Sheet (CSV). Completed tasks stay in the Sheet.

## Phases
- T1: Tasks basics (this plan: `plan.md`).
- T2: Repeating tasks and holidays.
- T3: Dashboard, calendar, daily digest, import.
