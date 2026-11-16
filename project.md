# Group ERP Platform: Project Blueprint

Internal platform for a group of companies. One shared core + many small plug-in apps
(task management, travel, accounting/audit tasks, etc.). Same users, same look and feel.
10-20 concurrent users. Some external users (limited access).User shall have Sandbox (separate environment) for Testing.

\---

## 1\. Tech Stack (do not change without asking)

* Python 3.12+, **Django 5.x** (server-rendered)
* **HTMX** for interactivity. No React/Vue/SPA.
* **Tailwind CSS** (or Bootstrap) for the common look
* **PostgreSQL** (single database for all apps)
* **django-q2** for background jobs (email, WhatsApp, reports)
* **django-simple-history** for audit trail
* **django-axes** (login lockout) + **django-otp** (2FA, mandatory for finance/audit apps)
* **openpyxl** (Excel), **WeasyPrint** (PDF)
* **Docker Compose**: web (gunicorn), db (postgres), nginx
* Tests: **pytest + pytest-django**

\---

## 2\. Folder Structure

```
erp/
├── config/                 settings (base/dev/prod), urls, wsgi
├── core/                   built ONCE, used by all apps
│   ├── accounts/           login, users, roles, 2FA, invite-only signup
│   ├── masters/            Company, Branch, Department, Employee, Vendor, Customer, CostCentre
│   ├── access/             company-level + record-level permission rules
│   ├── approvals/          generic approval engine
│   ├── notifications/      notify() -> email + WhatsApp
│   ├── files/              secure private uploads
│   ├── audit/              history helpers
│   ├── reports/            Excel/PDF helpers
│   ├── registry.py         app registry (menu, icon, permissions, dashboard widget)
│   └── templates/          base layout, sidebar, home dashboard, shared components
├── apps/
│   ├── \_starter/           skeleton to copy for every new app
│   ├── tasks/              pilot app (build first)
│   └── travel/ ...         future apps
├── docker/                 Dockerfile, compose, nginx conf
├── tests/
├── PROJECT.md              this file
└── manage.py
```

\---

## 3\. Golden Rules (follow in EVERY app)

1. **Apps depend on `core`, never directly on each other.** If app A needs app B's data,
go through a small interface/service function, not a direct model import.
2. **All shared data lives in `core.masters`.** Never copy company, employee, vendor, or
cost-centre data into an app. Use ForeignKey to the master.
3. **Every app model extends `core.access.BaseModel`**, which provides: `company`,
`created\_by`, `created\_at`, `updated\_at`, `is\_active`, and history tracking.
4. **Never write permission logic inside an app.** Use the core access layer only
(see section 4).
5. **Every app template extends `core/templates/base.html`.** No custom page layouts,
no per-app CSS frameworks. Use shared components only.
6. **Every app registers itself in `registry.py`** (name, icon, URL, permissions, optional
dashboard widget). Sidebar and home dashboard are built from the registry automatically.
7. **Use the core services, don't reinvent:** `approvals`, `notify()`, `files`, `reports`.
8. **No raw SQL.** Django ORM only.
9. **Business logic goes in `services.py`**, not in views or templates.
10. **Every new feature needs tests**, especially anything touching permissions.
11. **Never hardcode secrets.** Use environment variables.
12. Keep views small. Prefer class-based views and HTMX partial templates.

\---

## 4\. Access Control (3 layers)

1. **App level**: which apps a user can open (via role).
2. **Company level**: user sees only data of companies assigned to them. Enforced
automatically through a custom manager on `BaseModel` (queries are auto-filtered).
3. **Record level**:

   * Roles can be flagged "own records only" (user sees only what they created/are assigned).
   * Approvers see records waiting for their approval.

External users = same user table, with a restricted role limited to specific apps/companies.
No public sign-up: users are invited/created by admin only.

\---

## 5\. Core Services

### Approvals (generic engine)

* Any record of any app can be submitted for approval.
* Configurable levels and approvers per app/company (e.g., Manager -> Finance).
* States: Draft -> Submitted -> Approved / Rejected / Returned.
* Every action logged with user, time, and remarks.

### Notifications

* Single function: `notify(user, title, message, channels=\["email", "whatsapp"])`.
* Runs as a background job (django-q2).
* WhatsApp via provider API (Meta Cloud API or Twilio) using pre-approved templates.

### Files

* Stored privately, never publicly. Served only through a permission-checked view.
* Linked to any record via a generic relation. Limit file types and size.

### Reports

* Helpers for Excel and PDF export, with common header/footer and company branding.

### Audit

* Every model change recorded (who, what, when, old/new). History is viewable per record.

### Dashboard

* Home page shows widgets contributed by each registered app.

\---

## 6\. Core Data Model (start here)

* **Company**: name, code, address, tax IDs-PAN,TAN,GSTN,CIN, is\_active
* **Branch**: company FK, name, code
* **Department**: company FK, name
* **CostCentre**: company FK, code, name
* **Employee**: user FK (optional), company, branch, department, designation, reports\_to, profile\_photo (image, served through the permission-checked files view)
* **Vendor / Customer**: company, name, tax IDs, contact, bank details
* **User** (custom, extends AbstractUser): is\_external, companies (M2M), roles
* **Role**: name, apps allowed, own\_records\_only flag
* **ApprovalFlow / ApprovalStep / ApprovalRequest / ApprovalAction**
* **FileAttachment**: generic relation, file, uploaded\_by
* **Notification log**: user, channel, status

\---

## 7\. New App Checklist (copy from `apps/\_starter`)

* \[ ] Copy `\_starter` to `apps/<name>`
* \[ ] Models extend `BaseModel`, use masters via FK
* \[ ] Register in `core/registry.py` (menu, icon, permissions, widget)
* \[ ] Templates extend `base.html`, use shared components
* \[ ] Use core approvals / notify / files / reports where needed
* \[ ] Add permission tests (company isolation, own-records, approver access)
* \[ ] Add to `INSTALLED\_APPS` and URL config
* \[ ] Run migrations and tests

\---

## 8\. Build Order

**Phase 1: Foundation**

1. Docker + Django + PostgreSQL project skeleton, settings split
2. Custom user model, login, lockout, 2FA, invite-only users
3. Masters (Company, Branch, Department, CostCentre, Employee, Vendor, Customer)
4. Base layout, sidebar, home dashboard, app registry
5. Access layer (BaseModel, company filter, record-level rules) + tests

**Phase 2: Core services**
6. Audit (simple-history)
7. Files
8. Notifications (email first, WhatsApp later)
9. Approvals engine
10. Reports helpers

**Phase 3: Pilot**
11. Build **Task Management** app using only the core. Fix gaps in core.
12. Create the final `\_starter` template from what was learned.

**Phase 4: Scale**
13. Add other apps one by one (Travel, Accounting tasks, Audit, ...)

\---

## 9\. Deployment

* Docker Compose: web, db, nginx. Works on own server or cloud VPS.
* HTTPS (Let's Encrypt), automatic daily PostgreSQL backups, tested restore.
* Separate staging environment before production.
* Env vars via `.env` (never committed).

\---

## 10\. Working Instructions for Claude Code

* Work **one phase/step at a time**. Confirm before moving to the next.
* Before writing code, briefly state the plan and the files to be changed.
* Follow the Golden Rules strictly. If a request conflicts with them, point it out first.
* Write tests along with code and run them before saying a step is done.
* Commit to Git after each completed step with a clear message.
* Ask when requirements are unclear instead of guessing, especially for finance,
approval, and permission logic.

