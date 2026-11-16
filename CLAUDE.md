\# Project

Reusable apps for other Django projects.



\# Stack

\- Python/Django, HTMX, Alpine.js, DaisyUI, uv (dependencies)

\- Database: SQLite for dev/test, PostgreSQL for production. No database-specific code.

\- Separate environments: development, testing, production (settings via .env)

\- Each app: `<app>/docs/project.md` = scope \& requirements, `<app>/docs/plan.md` = current phase plan



\# Workflow

Plan → Build → Test, one phase at a time.

\- Plan: read `docs/project.md`, write/update `docs/plan.md` for the next phase only. Before finalising, run the `grill-me` skill and get my confirmation.

\- Build: implement only that phase.

\- Test: write and run tests before moving on.

\- End of phase: run `/code-review` or `/simplify`, commit to Git, and update "Current phase" (1 short line) in that app's `CLAUDE.md`.



\# Skills

\- For front-end and screens use: frontend-design, HTMX, daisyui.



\# Coding conventions

\- Naming: snake\_case for functions/variables, PascalCase for classes, descriptive names (no `df1`, `temp`, `x`).

\- Specific, user-facing error messages. No bare `except:`.

\- Log errors before raising or displaying them.

\- Add tooltips for better UX.

\- Business logic in `services.py`, not in views or templates.

\- Permissions: use the shared access layer only. Never write permission checks inside an app. Test who can see what.

\- Migrations: never edit an old one, create a new one.

\- Never commit `.env` or secrets.



\# Ask first

Ask me before: adding a new package, changing database structure, or deleting data/files.



\# Reusable components

\- For any tabular data (filters, search, sort, pages, CSV) use the `django-datatable` package. Do not hand-write tables.

\- Install from GitHub, not a local folder:

&#x20; `uv add "django-datatable @ git+https://github.com/saurabhtiki/django-datatable"`

\- Setup and usage: https://github.com/saurabhtiki/django-datatable (README.md)

\- Never edit a copy inside this app. Package changes are made in the django-datatable repo only.



\# Answers \& Plan

\- Keep language short and simple, as a layman can understand. Give small examples.

