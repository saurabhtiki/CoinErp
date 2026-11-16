# Plan: Phase 1 — Foundation (confirmed; done, Steps 1–5 + review fixes)

Goal: a working, secure shell of the ERP. Users can log in, see only their companies,
and see a sidebar + home dashboard. No business apps yet.

We build it in 5 small steps. Each step = code + tests + Git commit, and I stop for your OK.

---

## Step 1. Project skeleton

- `uv init`, Django 5.x project in `erp/` layout from project.md (`config/`, `core/`, `apps/`).
- Settings split: `config/settings/base.py`, `dev.py`, `test.py`, `prod.py`. Values come from `.env`.
  - dev/test: SQLite. prod: PostgreSQL. (Example: `DATABASE_URL=sqlite:///db.sqlite3`)
- `.env.example` committed, `.env` git-ignored.
- `docker/`: Dockerfile, `compose.yml` (web = gunicorn, db = postgres, nginx).
- pytest + pytest-django set up, one smoke test ("home page needs login").
- `git init` + first commit.

## Step 2. Users and login

- Custom `User` (extends AbstractUser): `is_external`, `companies` (M2M), `roles` (M2M).
- `Role`: name, allowed apps, `own_records_only`, `requires_2fa`.
- Login / logout / password reset pages (DaisyUI look).
- django-axes: lock account after 5 wrong passwords (example: locked for 30 min).
- django-otp: TOTP (Google Authenticator). Forced only when a user's role says `requires_2fa`.
- Invite-only: admin creates user -> user gets an email link to set their own password.
  No public sign-up page.
- Built: `core/accounts` (User, Role, 2FA) and a starter `Company` in `core/masters`
  (name, code, is_active). Step 4 adds address and tax IDs to it.

## Step 3. Access layer (moved before masters, see note)

- `core.access.BaseModel` (abstract): `company`, `created_by`, `created_at`, `updated_at`, `is_active`.
- Company-filtered manager: `Model.objects.for_user(user)` returns only rows of that user's companies.
- Record-level rule: role with `own_records_only` sees only rows it created / is assigned to.
- App-level rule: view mixin `AppAccessRequiredMixin` checks the user's role allows the app.
- Tests: user of Company A cannot see Company B data; own-records user sees only own rows.
- Built: `core/access` (models.py BaseModel + `for_user`, services.py rules, mixins.py
  `AppAccessRequiredMixin` + `VisibleRowsMixin`). Own-records applies only when every role
  that opens the app says so. Tests use a test-only `tests/access_demo` app.

## Step 4. Masters

- Company (name, code, address, PAN, TAN, GSTN, CIN, is_active)
- Branch, Department, CostCentre (each linked to a Company)
- Employee (optional user link, company, branch, department, designation, reports_to, profile_photo)
- Vendor, Customer (company, name, tax IDs, contact, bank details)
- Managed via Django admin first; list screens with `django-datatable`.
- Format checks: PAN, GSTN, etc. (example: PAN = `ABCDE1234F`).
- Built: models in `core/masters/models.py`, ID checks in `fields.py` (also: GSTN must contain the PAN,
  codes unique per company, linked records must be from the same company, photo JPG/PNG up to 2 MB).
  Admin goes through `core/access/admin.py` (rights from roles: app code `masters`). Bank details need
  the `masters.view_bank_details` permission. One list screen for all masters at `/masters/<name>/`.
  A simple `base.html` was added for the list screens; Step 5 adds the sidebar.
- Change (agreed 2026-11-16): roles are per company. `accounts.CompanyRole` = user + company + role
  (e.g. Ravi: Acme → Manager, Globex → Admin); it replaces User.companies/User.roles. Access rules
  are applied company by company. One login can have one Employee record per company.

## Step 5. Layout, registry, dashboard

- `core/templates/base.html`: DaisyUI + HTMX + Alpine, sidebar, top bar, user menu.
- `core/registry.py`: each app registers name, icon, URL, permission, optional dashboard widget.
- Sidebar and home dashboard built from the registry, showing only apps the user may open.
- Tests: user sees only allowed apps in the sidebar.
- Built: `core/registry.py` (AppEntry, register in AppConfig.ready, `apps_for_user`, `dashboard_cards`);
  access layer `apps_user_can_open` (one query); sidebar via `core.context_processors.app_menu`;
  user menu (change password, Admin for staff, sign out); Masters widget counts in `masters/services.py`.
  A failing widget shows a note and is logged, the dashboard still opens.

---

## Packages to add (need your OK)

django, django-environ, psycopg (prod), gunicorn, django-axes, django-otp, qrcode (2FA QR),
django-htmx, django-datatable (from GitHub), pytest, pytest-django.
(django-simple-history, django-q2, openpyxl, WeasyPrint come in Phase 2.)

## Decisions (agreed 2026-11-16)

1. DB: SQLite for dev/test, PostgreSQL (Docker) for staging/prod.
2. UI: DaisyUI + Tailwind + HTMX + Alpine.js.
3. Tailwind built with `django-tailwind-cli` (no Node).
4. This is one ERP project; apps stay self-contained. CLAUDE.md to be updated to say so.
5. Access layer (step 3) built before Masters (step 4).
6. Login with email address.
7. `requires_2fa` flag on Role; superusers always need 2FA.
8. Lockout: 5 wrong passwords -> locked 30 min; admin can unlock.
9. Invite: admin creates user -> Django's built-in set-password email link (default expiry, nothing custom).
10. Vendor/Customer belong to one company.
11. Bank details: plain fields, visible only with a "view bank details" permission.
12. Sandbox = separate staging deployment (own URL + DB), same Docker setup. Deployed later.
13. Packages approved: django, django-environ, psycopg, gunicorn, django-axes, django-otp, qrcode,
    django-htmx, django-tailwind-cli, django-datatable (GitHub), pytest, pytest-django.
14. Git: repo `github.com/saurabhtiki/CoinERP` (public), branch `main`. Commit + push after each step.
15. Never commit `.env`, DB files, or secrets (repo is public).
16. Superuser sees all companies; everyone else only companies where they have a role (role per company).
17. External user = `is_external=True`; no admin site; only role's apps + assigned companies.
18. Locale: Asia/Kolkata, en-IN, dates `DD-MM-YYYY`, currency INR.
19. Employee gets `employee_code` (unique per company), email, mobile.

Note: "own records only" in Phase 1 = rows the user created. Each app can later add its own
"assigned to" field through the access layer.
