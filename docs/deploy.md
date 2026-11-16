# Deploying CoinErp

One server (Linux, with Docker) runs three small projects:

| Project | What it is | Port (this machine only) |
|---|---|---|
| `coinerp-prod` | The real ERP | 8000 |
| `coinerp-sandbox` | Test copy with fake data | 8001 |
| `coinerp-edge` | Caddy: HTTPS for both, the only public door (80, 443) | 80, 443 |

Start them in this order: **prod, sandbox, edge**.

## 1. Before you start
- A Linux server with Docker and git installed.
- Two DNS names pointing at the server's IP, e.g. `erp.example.com` and `sandbox.erp.example.com`.
- Ports 80 and 443 open to the internet. Nothing else.

## 2. Get the code
```bash
git clone https://github.com/saurabhtiki/CoinErp.git
cd CoinErp
```

## 3. Production
```bash
cp .env.prod.example .env.prod
```
Edit `.env.prod`: set a new `SECRET_KEY`, the real domain in `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `SITE_URL`, a strong database password (in **both** `POSTGRES_PASSWORD` and `DATABASE_URL`), and the mail settings.

```bash
sh docker/deploy.sh prod
docker compose -p coinerp-prod --env-file .env.prod -f docker/compose.yml exec web python manage.py createsuperuser
```
The first start runs the migrations and sets up the daily jobs (tasks at 6:00, backup at 2:00).

## 4. Sandbox
```bash
cp .env.sandbox.example .env.sandbox
```
Edit it: a **different** `SECRET_KEY`, database password and the sandbox domain. Set `DEMO_PASSWORD`.
```bash
sh docker/deploy.sh sandbox
docker compose -p coinerp-sandbox --env-file .env.sandbox -f docker/compose.yml exec web python manage.py reset_sandbox --yes
```
`reset_sandbox` wipes the sandbox and loads fake data. It refuses to run on production.

## 5. HTTPS (Caddy)
```bash
cp .env.edge.example .env.edge
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'the-sandbox-password'
```
Put the hash in `SANDBOX_PASSWORD_HASH` (keep the single quotes). Fill `ACME_EMAIL`, `PROD_DOMAIN`, `SANDBOX_DOMAIN`, `SANDBOX_USER`.
```bash
docker compose -f docker/caddy/compose.yml up -d
```
Caddy gets the certificates by itself and renews them. Open both sites in a browser to check.

## 6. Raise HSTS
HSTS starts at 1 hour so a mistake is easy to undo. When HTTPS has worked for a week, set `SECURE_HSTS_SECONDS=31536000` in `.env.prod` and run `sh docker/deploy.sh prod`.

## 7. Updating later
```bash
sh docker/deploy.sh prod
```
It pulls the code, takes a backup, builds, restarts (migrations run on start) and waits for the health check. If it says **NOT healthy**, read the logs it prints.

## 8. Health check
`/healthz/` answers `ok` (200) when the app and database work, and `503` with a clear message when the database is down. It needs no login and works over plain http.
Point an uptime monitor (UptimeRobot, Better Stack) at `https://erp.example.com/healthz/`.

## 9. Backups
- Daily at 2:00 am. Zip = database + uploaded files. Kept: newest 14, plus one per week for 8 weeks.
- Superusers see them at **Backups** in the user menu, and can download or run one now.
- **Download a copy off the server regularly.** A backup on the same machine does not survive a lost server.

Restore (on the server only, it replaces everything):
```bash
PROJECT=coinerp-prod ENV_FILE=.env.prod sh docker/restore_backup.sh /path/to/backup.zip
```
Try a restore into the **sandbox** first (`PROJECT=coinerp-sandbox ENV_FILE=.env.sandbox`) to be sure the file works.

## 10. Hardening checklist
- [ ] Firewall: allow only 22 (SSH), 80, 443. `ufw allow 22,80,443/tcp && ufw enable`
- [ ] SSH: keys only, no password login, no root login.
- [ ] `.env.prod`, `.env.sandbox`, `.env.edge` are `chmod 600` and never committed.
- [ ] Automatic security updates on (`unattended-upgrades`).
- [ ] Uptime monitor on `/healthz/`.
- [ ] A backup copy stored off the server.
- [ ] Every superuser has 2FA set up (the app forces it).
