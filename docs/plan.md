# Plan: Core Step 11 — Deployment + Sandbox (confirmed 2026-11-16)

Goal: run the ERP safely on a real server, with a separate Sandbox for testing and daily backups.
Earlier plans: `docs/phase1-plan.md`, `docs/phase2-plan.md`.
Target: a Linux VPS (Hostinger or DigitalOcean) with Docker. Domain names are set in `.env`
(placeholders in files: `erp.example.com`, `sandbox.erp.example.com`).

Each part = code + tests + commit, then I stop for your OK.

---

## Part A. Production and Sandbox side by side

- Same compose file, two `.env` files, two project names (`coinerp-prod`, `coinerp-sandbox`).
  Each has its own database, uploaded-files volume and port.
- Setting `ENVIRONMENT=sandbox` shows an orange bar "SANDBOX: test data only" on every page.
- Sandbox never sends real email: mails are written to the log and shown on a **Sent mail** screen
  (sandbox only). WhatsApp stays log-only.
- Sandbox is behind an extra shared password at Caddy.
- `load_demo_data`: fake companies, users with roles, tasks, approvals. No real data is ever copied.
- `reset_sandbox`: wipes the sandbox and reloads the demo data. **Refuses to run in production.**

## Part B. Backups

- `backup` container: every day at 2:00 am, database (`pg_dump`) + uploaded files (`private_media`).
- Keeps 14 daily + 8 weekly copies on the server. A failed backup emails the admin.
- Optional upload to cloud storage (S3 / Backblaze / Drive). Off until you give the storage details.
- **Backups page** (superuser only): list (date, size, status), **Download .zip** (plain zip, with a
  warning to keep it safe), **Backup now** (background job). Every download is written to history (who, when).
- `restore_backup.sh`: server script only, no button in the app. Warns that it overwrites the target database.
- Database change (ask before adding): one small table `BackupRecord` (file, size, status, created, downloaded by/when).

## Part C. HTTPS and safety

- Caddy replaces nginx: automatic Let's Encrypt certificates, sandbox password.
- HSTS, secure cookies, SSL redirect in production settings. `manage.py check --deploy` must pass.
- 2FA unchanged (only where an app requires it); checked to work behind HTTPS.

## Part D. Operations

- `/health/` page: checks the database, used by Docker and uptime monitors.
- `deploy.sh`: manual update (pull code, build, migrate, restart).
- `docs/deploy.md`: step-by-step server guide, plus a checklist for firewall, SSH keys, monitoring.

## Tests

- Banner shows only in sandbox; sandbox email is suppressed and listed on the Sent mail screen.
- `reset_sandbox` refuses to run when the environment is production.
- Only a superuser can open or download backups; the download is logged; other users get 404.
- Backup and restore round trip on a small database.
- `/health/` returns OK (and a clear error when the database is down).
- `check --deploy` passes with production settings.

## Packages

None planned. Caddy is a Docker image, not a Python package. I will ask first if one is needed.

## Decisions (agreed 2026-11-16)

1. Server: Hostinger / DigitalOcean VPS.
2. Sandbox data: fake demo data only (no masked copies of real data).
3. Sandbox protected by an extra shared password.
4. Sandbox never sends real email; log + Sent mail screen.
5. Backups: server folder, plus optional cloud upload (off until configured).
6. Daily 2:00 am, 14 daily + 8 weekly, failure alert by email.
7. HTTPS with Caddy.
8. 2FA only where an app requires it.
9. Manual `deploy.sh`.
10. Backups page: superuser only, downloads logged.
11. Plain zip download (no new package).
12. "Backup now" button.
13. Restore is a server script only.
14. Orange sandbox bar; `reset_sandbox` blocked in production.
15. Placeholder domain names; `/health/` page; hardening goes in a checklist, not code.

## Finish

`uv run pytest`, test the backup and restore with Docker on your PC, `/code-review`, commit,
update "Current phase" in `CLAUDE.md`.
