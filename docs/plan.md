# Plan: Phase 2 — Core services (confirmed 2026-11-16)

Goal: the shared services every app will use: history, files, notifications, approvals, reports.
No business app yet (Tasks comes in Phase 3). Phase 1 plan: `docs/phase1-plan.md`.

5 small steps. Each step = code + tests + commit + push, then I stop for your OK.
Services are tested on a test-only demo app (`tests/`), so nothing fake shows in the real menu.

---

## Step 6. Audit (history)

- `django-simple-history` on every `BaseModel` record (automatic), all masters, User, Role, CompanyRole.
- Records who, when, old value → new value. Passwords and 2FA secrets are never stored.
- `core/audit`: a **History** button/page per record. Visible to anyone who can see the record
  (checked through the access layer).
- Example: "Ravi changed Vendor *Steel Co* phone 98… → 99… on 16-11-2026 14:05".
- Tests: change is recorded with user; history hidden from users of other companies; no password in history.
- Built: history on `BaseModel` (`inherit=True`), Company, Role, CompanyRole, User (no password/last login).
  `core/audit` page `/history/<app>/<model>/<id>/` (rows via access layer `visible_records`, bank fields hidden via
  `hidden_fields`); History link on every master list row. Admin History button (`HistoryAdmin`) shows only
  listed rows and hides bank fields; view only (no revert). Records made before Step 6 start with no history.

## Step 7. Files

- `core/files`: `FileAttachment` (generic link to any record, file, uploaded_by, soft delete).
- Stored in the private folder (`private_media`), never a public URL.
- Download only through a permission-checked view: you can download if you can see the parent record.
- Allowed: PDF, JPG, PNG, XLSX, DOCX, CSV; max 10 MB. Clear error otherwise.
- Delete: uploader or staff; soft delete (hidden, kept, shows in history).
- Employee profile photo is served through the same checked view.
- Tests: other-company user gets "not found"; wrong type/size refused; deleted file not downloadable.
- Built: `core/files` (`FileAttachment` with history, random stored names; checks type, 10 MB and that the
  content matches the extension). `MEDIA_URL=/files/private/` so every file link goes through `PrivateFileView`
  (access layer `can_see_record`; PDF/images open in the browser, others download; `nosniff` + `sandbox`).
  Files page per record `/files/<app>/<model>/<id>/` (HTMX upload/delete), Files link on master rows.
  Single file fields opt in with `protect_file_field()` (Employee photo now; Company logo in Step 10).

## Step 8. Notifications

- `django-q2` with the database as queue (no Redis). Docker gets a `worker` container.
  In tests and on your PC jobs run immediately.
- `notify(user, title, message, channels=["email", "inapp"])` in `core/notifications/services.py`.
- Email now. WhatsApp = placeholder that logs "WhatsApp not set up yet" (built later).
- In-app **bell** in the top bar with unread count and a list (HTMX, mark as read).
- `NotificationLog`: user, channel, title, status, error, sent_at. Failed email retried 3 times.
- No per-user on/off switch for now.
- Tests: email sent and logged; failure logged and retried; bell shows only your own notifications.
- Built: `core/notifications` (`Notification` = bell message, `NotificationLog` = every send). `notify()` default
  channels email + in-app; email goes through `async_task` (django-q2, ORM queue; `Q_SYNC` runs it at once in
  dev/tests) and is tried 3 times (`NOTIFY_RETRY_WAITS`). Email links use `SITE_URL`. Bell in the top bar
  (unread badge, latest 8 via HTMX, `/notifications/` page, mark all read). Log is read-only in admin.
  Docker `worker` container runs `qcluster`.

## Step 9. Approvals engine

- `core/approvals`: `ApprovalFlow` (app + company), `ApprovalStep` (order, approver type, optional
  minimum amount), `ApprovalRequest`, `ApprovalAction` (user, time, action, remarks).
- Set up in Django admin. Example: "Tasks in Acme: Manager → Finance (over ₹1,00,000)".
- Approver per step: a named user, anyone with a role in that company, or the submitter's manager (`reports_to`).
- Steps run in order; any one approver at a step is enough.
- States: Draft → Submitted → Approved / Rejected / Returned.
  - Returned: back to submitter to edit and resubmit; starts again at step 1.
  - Rejected: final. Withdraw: allowed until someone acts.
- Nobody approves their own record; if the submitter is the only approver at a step, it goes to the next step.
- No approver found for a step → submit stops with a clear message
  ("No approver for step 'Manager' in Acme. Ask your admin.").
- Amount steps: an app tells the engine its amount field; steps with a minimum amount apply only above it.
- A submitted record keeps the steps it started with, even if the flow is changed later.
- Record locked from editing while Submitted or Approved.
- Approvers see records waiting for them, even if "own records only" would hide them (via the access layer).
- Remarks required for Reject and Return. Each action notifies the next person (uses `notify()`).
- **My approvals** in the sidebar with waiting count; Approve / Return / Reject with remarks (HTMX).
  Each record shows its approval trail.
- Tests: full Manager → Finance path; return and resubmit; reject; withdraw; self-approval skipped;
  no approver error; amount rule; flow change does not affect submitted records; other-company user
  cannot act; locked record cannot be edited.
- Built: `core/approvals` (models, `services.py` = submit / approve / send_back / reject / withdraw, admin to set
  up flows, read-only request list). Apps opt in with `ApprovableMixin` (+ optional `approval_amount_field`); saving
  a locked record raises, and admin makes it read-only. Approvers per step are worked out when the step starts;
  the submit checks every step has someone. Access layer: `can_act_on_approval`, `record_is_locked`, and
  `visible_rows` adds records waiting for the user. Screens: "My approvals" (sidebar badge, HTMX buttons) and a
  record panel (`/approvals/record/<app>/<model>/<id>/`) for app pages: status, trail, Submit / Withdraw.

## Step 10. Reports helpers

- `core/reports`: helpers for **Excel** (`openpyxl`) and **Word** (`python-docx`) and a printable **HTML** page.
- Common header: company name, address, GSTN, logo. Footer: "Printed by Ravi on 16-11-2026, page 1 of 3".
- New field `Company.logo` (optional, PNG/JPG, up to 1 MB; served through the checked files view).
  Without a logo, the header shows the name only.
- HTML report hides sidebar and buttons when printing; Ctrl+P → "Save as PDF" gives a PDF.
- PDF files from the server: later (WeasyPrint postponed).
- Tests: Excel/Word files open and contain header + rows; HTML page shows header; only visible rows exported.

---

## Packages to add (approved 2026-11-16)

django-simple-history, django-q2, openpyxl, python-docx.

## Decisions (agreed 2026-11-16)

1. 5 steps in blueprint order (6 Audit → 10 Reports); stop for OK after each.
2. No PDF package now; reports = Excel, Word, printable HTML. PDF later.
3. History on all business records, masters and access data; visible to whoever can see the record.
4. Files: private folder, checked downloads, PDF/JPG/PNG/XLSX/DOCX/CSV, 10 MB, soft delete.
5. Background jobs: django-q2, database queue, `worker` container.
6. Notifications: email + in-app bell now; WhatsApp later; 3 retries; no opt-out yet.
7. Approval flow per app + company; approver = user / role / manager; one approval per step.
8. Return restarts at step 1; reject is final; withdraw until first action; no self-approval; lock while in approval.
9. Optional minimum amount per step.
10. `Company.logo` added (database change approved).
11. Services tested with a test-only demo app.
12. No approver for a step → submit blocked with a clear message.
13. Submitted records keep their original steps.
14. "My approvals" screen in the sidebar.
