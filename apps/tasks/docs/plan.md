# Tasks: Phase T4 plan (Add actions, files and comments while creating)

Status (2026-11-17): T4 done. Part A and Part B built, tested and committed.
Still open from T3: Part D (import from the old Sheet), to be built when the CSV files are shared.

## Context
Today the **New task** and **New repeating task** forms only take the basic fields. Actions, files and links
can be added only after saving, from the side panel. In T4 both forms get **tabs**, and one click saves
everything together.

Work in 2 parts. Each part = code + tests + commit, then I stop for your OK.
Permissions: only the shared access layer and core files (`core/files/services.py`). No new checks in the app.

## Part A. New task with tabs (no database change)
Tabs at the top of the New task form:

```
[ Details ] [ Actions (2) ] [ Files & links (1) ] [ Comment ]
```

- **Details**: today's fields (company, title, owner, due date, reviewer, category, priority, collaborators,
  description).
- **Actions**: "+ Add action" adds a row (what, who, due date); ✕ removes it. A new row starts with
  who = the task owner and due date = the task due date. Rows are added in the browser (Alpine), with no server call.
- **Files & links**: choose one or more files (same rules as now: up to 10 MB each; PDF, JPG, PNG, Excel,
  Word, CSV) and add link rows (name + web address).
- **Comment**: the first comment (this already exists; it moves into its own tab).
- **Create task** sends everything at once (`hx-encoding="multipart/form-data"`).
- **Errors**: the tab that has an error gets a red dot (●), and the form opens on the first such tab.
  Example: "Actions ●" with "Row 2: pick who does this action". Nothing is saved until all of it is right.
- **Saving** (`services.create_task(..., actions=[...], links=[...], files=[...])`, one transaction):
  all files are checked first; then the task is saved, followed by its actions, links, comment and files.
  If anything fails, nothing is saved.
- Notifications: same as today, plus "New action for you" to each action owner who is not the task owner
  (the task owner already gets "New task for you").
- Tooltips on every tab and button.

## Part B. Repeating task with tabs (database change: ask-first item)
The same tabs on the New / Edit repeating task panel:

```
[ Details ] [ Actions (2) ] [ Files & links (1) ] [ Comments (3) ]
```

- **Actions**: same row editor as Part A, but "days before the due date" instead of a date (as today).
  On an existing rule the current add/remove list moves into this tab.
- **Files & links**: files are kept on the rule with core files (`FileAttachment`, no new table).
  Links are kept in a **new table `RecurringLink`** (rule, name, web address).
  Only people who can change the rule (owner, creator, owner's manager, admin) add or remove them;
  collaborators can view and download.
- **Comments**: a discussion about the rule itself, e.g. "Should we move this to day 10?".
  **New table `RecurringComment`** (rule, text, who, when). Works like task comments: anyone who can see the rule
  can write; the people on the rule get a bell. **Not copied** to the tasks. On the New form it is an optional
  first comment. Tips every task should carry go in the rule's Description (already copied).
- **What each new task gets** from its rule (in `_make_task`): its actions (as today), a link row for each rule
  link, and a **copy of each rule file**.
  - Why copy the files: a file can belong to only one record in core files, and the download check follows that
    record. With a copy, everyone who can see the task can download it, and an old task keeps the file
    it was done with even if the rule's file is changed later. Cost: one copy per task (e.g. a 1 MB template on a
    monthly rule = 12 MB a year).
- Changing a rule's files or links affects **future tasks only**. Tasks already made keep what they have (same as actions today).
- On an **existing** task or rule, adding or removing an action, file, link or comment saves at once (as today).
  Only the New forms save everything with one click.
- One new migration: `RecurringLink` and `RecurringComment` tables. No old migration is edited.

## Rule change for actions (Parts A and B)
- An action can't be due after its task: "Action due date can't be after the task's due date (25 Nov)."
  Checked in `add_action` and the New task form. For rules: "days before" is 0 or more, so this is always true.

## Tests (`tests/test_tasks_create_tabs.py`, `tests/test_tasks_rule_tabs.py`)
- New task: saves task + 2 actions + 1 link + 1 file + comment in one go; a bad action row → nothing
  saved and the error is shown on the Actions tab; a file too big or of the wrong type → nothing saved; an
  action owner from another company is refused; action owners get their notification.
- New task: an action due after the task → refused with the message; same in the side panel.
- Rule: new rule with actions, a link, a file and a comment in one go; the daily job makes a task that has the
  actions, the link and its own copy of the file, but not the rule's comments; editing the rule changes only
  later tasks; a collaborator cannot add or remove rule files/links but can download and comment; an outsider
  cannot see, comment on, or download anything of the rule.
- Outsider cannot see or download the task's files (existing rule, checked again).

## Packages / database
- No new package.
- Database: Part B only, two new tables (`RecurringLink`, `RecurringComment`). Agreed 2026-11-17.

## Decisions (agreed in grill-me, 2026-11-17)
1. Tabs on both New forms; one click saves everything.
2. Rule files are **copied** to each task (not shared).
3. Rule comments = discussion on the rule only, not copied to tasks.
4. An action can't be due after its task.
5. On existing tasks/rules, tab changes save at once (as today).
6. Only people who can change a rule add/remove its files and links.
7. 2 parts, stop for OK after each.

## Built differently from the plan (small)
- Rule files: the "only people who can change the rule" check lives in the shared access layer
  (`can_change_files`): a model can say `files_by_managers_only = True`. On such a record anyone who may change it
  can also remove any of its files (not only the uploader).
- Fixed on the way: the task panel's Files tab did not show the Upload form; the New task form's early
  "action after the task" check compared with the wrong date (the save still caught it).
- An action row whose person list is empty now says "pick who does it" instead of vanishing.

## Finish
`uv run pytest`, click through in the browser (create a task with all tabs, create a rule with all tabs, run
"Create due tasks now", open the new task), `/code-review`, commit, set "Current phase" in `apps/tasks/CLAUDE.md`
and the root `CLAUDE.md`.
