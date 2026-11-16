# Tasks: Phase T1 plan (Tasks basics)

Scope: one-time tasks only. No repeating rules, dashboard, calendar or import yet (T2, T3).

## 1. Core change: "involved" people can see a record
- `core/access/models.py`: `BaseModel.involved_filter(user)` returns an extra filter, default none.
- `core/access/services.py` → `visible_rows()`: in "own records only" companies, also show rows
  matching `involved_filter(user)`.
- `core/masters/services.py`: `team_user_ids(user)` = users who report to this user, all levels.
- Tests in `tests/test_access.py` with the demo `Note` model.

## 2. App skeleton
- `apps/tasks/`: `apps.py` (registers menu entry, code `tasks`), `models.py`, `services.py`, `forms.py`,
  `views.py`, `urls.py`, `admin.py`, `templates/tasks/`.
- Add to `INSTALLED_APPS` and `config/urls.py` (`tasks/`). Add a tasks icon in `nav_tags.py`.

## 3. Tables
- `TaskCategory`: name (unique per company).
- `Task`: number, title, description, owner, reviewer, category, priority, status, due_date,
  completed_at, collaborators, due_date_changes.
  (`recurring_task` and `period_label` are added in T2.)
- `TaskAction`: task, title, owner, due_date, is_done.
- `TaskComment`: task, text, is_system.
- `TaskLink`: task, label, url.

## 4. Business rules (`services.py`)
- `create_task`, `update_task`: comment required if due date changes or status becomes Blocked;
  counter +1 and a system note on each date change.
- `mark_done`: no reviewer → Completed; with reviewer → Under Review, reviewer is told.
  Reviewer (or admin) completes it.
- `add_comment`, `add_action`, `toggle_action`, `add_link`, `remove_link`.
- Task number: next number per company, `TSK-0001`.
- Owner, reviewer, collaborators must be people of the task's company.
- `notify()` on: assigned (owner, reviewer, collaborators), comment added (everyone on the task
  except the writer), sent for review.

## 5. Screens
- My tasks (I am owner, reviewer, collaborator or have an action), Assigned by me (I created, owner is
  someone else), All tasks (everything I may see). Built with django-datatable: search, status filter,
  quick filters (due today, next 7 days, overdue), CSV export, Done button per row.
- Side panel (HTMX) for New task and task detail: fields, then tabs Actions, Files, Comments.
  Files tab = core files panel (upload) + links.
- Tooltips on buttons. Clear error messages.

## 6. Tests (`tests/test_tasks.py`)
- Who sees what: owner, collaborator, reviewer, action owner, manager, admin, outsider (404), other company (404).
- Collaborator can comment and upload a file; outsider cannot.
- Comment-required rule; date-change counter; Done with and without reviewer.
- People from another company cannot be owner or collaborator.
- Notifications are sent to the right people.

## 7. Finish
`uv run pytest`, click through in the browser, `/code-review`, commit, set "Current phase" in `apps/tasks/CLAUDE.md`.
