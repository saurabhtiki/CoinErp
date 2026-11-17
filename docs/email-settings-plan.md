# Plan: Email settings in Admin (built 2026-11-17: E1 + E2 done)

Goal: the group admin sets up outgoing email on one Admin screen, tests it with one button,
and nobody has to edit `.env` or restart the server. One mailbox sends mail for all companies.

Example: Saurabh opens Admin → Email settings, types `smtp.gmail.com`, `587`, `coin@yourcompany.com`,
the App Password and "From: Coin", presses **Send test email**, and gets the test mail in his inbox
(or a plain message such as "Gmail refused the password: use an App Password, not your normal one").

---

## What the admin sees

One page **Admin → Email settings** (only one record; superuser only):

| Field | Example | Tooltip |
|---|---|---|
| Sending on | ticked | Untick to stop all emails (the bell still works) |
| Mail server | smtp.gmail.com | Your provider's SMTP server |
| Port | 587 | 587 (TLS) is usual; 465 for SSL |
| Security | TLS / SSL / None | TLS for port 587, SSL for 465 |
| Login (mailbox) | coin@yourcompany.com | The mailbox that sends |
| Password | ●●●● saved | App Password. Leave blank to keep the saved one |
| From name | Coin | Name people see as sender |
| From address | coin@yourcompany.com | Usually the same as the login |
| Reply-to | (optional) | Where replies go, e.g. office@yourcompany.com |

Buttons: **Save**, **Send test email** (to the admin's own address). Shown at the top:
"Last test: OK on 18 Nov 10:05" or the last error in plain words.

## Rules

- The password is stored **encrypted**, never shown again, never in History, never in logs.
- The encryption key lives in `.env` (`EMAIL_SETTINGS_KEY`), separate from the database.
  A stolen database copy alone cannot reveal the password.
- If nothing is saved on the screen yet, the current `.env` email settings keep working (no break on the server).
- The **sandbox never sends real mail** (stays as today: shown on the "Sent mail" page).
- On your PC (development) normal mail is still only printed; the **Send test email** button does send
  for real, so you can check the settings before going live.
- Changes are recorded in History (who changed the server/login and when; not the password itself).
- Errors are logged first, then shown in plain words (wrong password, server not reachable, port blocked).
- **Key lost or changed:** the password cannot be read -> no sending, error logged, red note on the page:
  "Password can't be read, please type it again". No crash, no guessing.
- **Sending off:** emails are skipped and logged as "Skipped: email is switched off". Not sent later. Bell still works.
- **Emails keep failing:** the superuser gets a bell message (not email), at most once a day:
  "Emails are failing: check Email settings".
- **Saving never sends a test by itself.** Testing is only through the button.
- Only the superuser sees or changes the screen. One sender for all companies (no per-company sender for now).

## How it works (short)

- New table `EmailSettings` (one row) in `core/notifications`.
- A small mail "backend" reads that row for each send, so every app (Tasks today, more later) uses it
  without any change. Retries (3 tries) and the email log stay as they are.

## Approved (2026-11-17)

1. **New package:** `cryptography`, to encrypt the password.
2. **New database table:** `EmailSettings`.

## Steps

- **E1** Table, encryption, Admin screen with tooltips, History without the password. Tests.
- **E2** Mail backend uses the screen's settings (fallback to `.env`), **Send test email** button,
  plain error messages. Tests: right settings used, password never in page/log/history, sandbox never sends,
  only superuser sees the screen, key lost -> warning, sending off -> skipped, failing -> one bell a day.
- Then review, commit, and update `.env.example` / `docs/deploy.md` (`EMAIL_SETTINGS_KEY`).
