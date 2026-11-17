# Tasks: Phase T5 plan (Dashboard: open actions, drill-down, filters)

Status (2026-11-17): Part A done (filters, drill-down). Part B (open actions) waiting for OK.
Still open from T3: Part D (import from the old Sheet), to be built when the CSV files are shared.
T1-T4 are done (see git history for their plans).

## Context
Today the dashboard has 5 task cards, 2 charts and a People table. Only the cards can be clicked.
There are no filters and no actions anywhere on it, and there is no page that lists actions.

Work in 2 parts. Each part = code + tests + commit, then I stop for your OK.
Permissions: everything counts only tasks the user may see (`Task.objects.for_user` / `visible_tasks`).
No new checks in the app.

## Part A. Filters and drill-down for tasks
**Filter bar** at the top of the dashboard. It changes cards, charts and the People table:

```
Company [All v]  Person [All v]  Category [All v]  Priority [All v]   [Clear]
```

- Company: only the user's Tasks companies. Person: the people in the user's People table (task owner).
  Category and Priority: as on tasks.
- The filters live in the address, e.g. `/tasks/dashboard/?company=2&person=5`. Not saved anywhere.
  Changing one reloads the page part with HTMX and updates the address.
- A wrong or not-allowed value (e.g. a company that is not yours) is ignored, with a short message.

**Drill-down:** every number is a link to the task list, and the filters go with it.
- Cards: as today, plus the filters. Example: Company = Acme, click "Overdue" -> Acme's overdue tasks.
- Chart bars: click "Blocked" -> blocked open tasks; click "GST" -> open GST tasks.
- People table: Het's "Open" -> Het's open tasks, "Overdue" -> Het's overdue tasks,
  "Done this month" -> Het's tasks completed this month.
- The task list learns the same extra filters (`company`, `person`, and "open only" / "done this month"),
  applied before the table's own filters. A small note on top of the list says what is applied, with a
  "Show all" link to drop it.

## Part B. Open actions
**Open action** = not ticked done, on a task that is active and not completed, which the user may see.

**4 new cards** (a second row, "Actions"):
- Overdue actions, Due today, Next 7 days, My open actions (actions given to me).

**People table:** 2 new columns, "Open actions" and "Overdue actions" (by the action's person).
Example: Amar -> Open actions 3, Overdue actions 1.

**New Actions list** (`/tasks/actions/`, also a tab next to Calendar), built with django-datatable:
- Columns: Action, Task, Person, Due date, When (overdue / today / next 7 days / later). Search, sort, CSV.
- Shortcuts: All, Due today, Next 7 days, Overdue, Mine.
- Clicking a row opens that task's panel on the Actions tab, where it can be ticked done.
- Every action number on the dashboard links here, with the filters. The Person filter means the
  action's person (on tasks it means the task owner).

## Tests (`tests/test_tasks_dashboard_t5.py`)
- Each filter changes the cards, charts and People table; Clear brings all back.
- A company or person the user may not see is ignored; outsiders' tasks/actions never count.
- Drill-down links carry the filters, and the list shows exactly the counted tasks (count on card = rows in list).
- Open actions: done actions, actions on completed tasks and on tasks the user can't see are not counted.
- Actions list: shortcuts, row opens the panel on Actions, a user sees only actions on tasks they may see.

## Packages / database
- No new package. No database change.

## Decisions (agreed in grill-me, 2026-11-17)
1. Open action = not done, on an open task the user may see.
2. 4 action cards + 2 action columns in the People table.
3. New Actions list + tab; a row opens the task panel on Actions.
4. Every number on the dashboard is clickable (cards, chart bars, People table).
5. Filters: Company, Person, Category, Priority; they go with every drill-down.
6. Filters live in the address only; a Clear button resets them.
7. 2 parts, stop for OK after each.

## Built differently from the plan (small)
- Person filter offers everyone who owns a task you may see (not only the People table), so a member can
  also pick a colleague whose shared task they see.
- A refused filter shows a yellow note on the page (not a pop-up message), so it is seen after an HTMX change.
- After a filter change the address may hold empty filters, e.g. `?company=&priority=high`. Harmless.

## Finish
`uv run pytest`, click through in the browser (filters, each kind of drill-down, Actions list), `/code-review`,
commit, set "Current phase" in `apps/tasks/CLAUDE.md` and the root `CLAUDE.md`.
