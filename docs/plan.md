# Plan: Phase 1 — Foundation (DRAFT, not confirmed)

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

## Step 3. Access layer (moved before masters, see note)

- `core.access.BaseModel` (abstract): `company`, `created_by`, `created_at`, `updated_at`, `is_active`.
- Company-filtered manager: `Model.objects.for_user(user)` returns only rows of that user's companies.
- Record-level rule: role with `own_records_only` sees only rows it created / is assigned to.
- App-level rule: view mixin `AppAccessRequiredMixin` checks the user's role allows the app.
- Tests: user of Company A cannot see Company B data; own-records user sees only own rows.

## Step 4. Masters

- Company (name, code, address, PAN, TAN, GSTN, CIN, is_active)
- Branch, Department, CostCentre (each linked to a Company)
- Employee (optional user link, company, branch, department, designation, reports_to, profile_photo)
- Vendor, Customer (company, name, tax IDs, contact, bank details)
- Managed via Django admin first; list screens with `django-datatable`.
- Format checks: PAN, GSTN, etc. (example: PAN = `ABCDE1234F`).

## Step 5. Layout, registry, dashboard

- `core/templates/base.html`: DaisyUI + HTMX + Alpine, sidebar, top bar, user menu.
- `core/registry.py`: each app registers name, icon, URL, permission, optional dashboard widget.
- Sidebar and home dashboard built from the registry, showing only apps the user may open.
- Tests: user sees only allowed apps in the sidebar.

---

## Packages to add (need your OK)

django, django-environ, psycopg (prod), gunicorn, django-axes, django-otp, qrcode (2FA QR),
django-htmx, django-datatable (from GitHub), pytest, pytest-django.
(django-simple-history, django-q2, openpyxl, WeasyPrint come in Phase 2.)

## Open questions

Listed in chat; answers will be written here before building.
