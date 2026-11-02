# InternLink Uganda - Employer Module

Backend implementation of the employer side of InternLink (WBS 4.4.1-4.4.5),
written in vanilla Python 3.11+ with no mandatory third-party dependencies.

It covers:

- employer registration, email verification, company profile and status (4.4.1-4.4.2)
- listing drafts, editing, controlled status changes, search and pagination (4.4.3)
- applicant review, CV download, shortlist/accept/reject with SR04 transitions (4.4.4)
- shortlist-only messaging (SR10)
- placement listing and completion (SR11)
- dashboard, in-app notifications and scheduled listing closure/deadline reminders
- an optional WSGI JSON API, SQLite and MySQL adapters, and a full test suite

## Layout

```
internlink_employer/
  api.py            WSGI JSON API
  handler.py        ACTIONS dispatch table + authenticated/public entry points
  session.py        token -> employer session, account/status checks
  security.py       password hashing, token hashing, reference bearer-token service
  validation.py     form cleaning and field-level validation
  errors.py         ModuleError, rule codes and DB integrity translation
  constants.py      state machines, limits, whitelists
  ports.py          Auth/Mailer/Notifier/Storage/MatchingCache interfaces
  adapters.py       stdlib reference adapters for local development
  context.py        AppContext dependency container
  db/               SQLite + optional MySQL adapters
  services/         company, listings, applications, messaging, placements, dashboard
schema/             reference schemas for SQLite and MySQL
tests/              unittest suite
run.py              local development server
```

## Quick start

Run the tests (stdlib only):

```powershell
python -m unittest discover -s tests -v
```

Start the local API:

```powershell
$env:INTERNLINK_TOKEN_SECRET = "replace-with-at-least-32-random-bytes"
python run.py --port 8080
```

The SQLite database is created at `data/internlink.db`, CV files are read from
`data/cvs` (outside the web root), and outgoing email is printed to the console.
Bearer tokens are issued by the Auth module; for local integration the
`ReferenceTokenService` is included so other modules can mint tokens:

```python
from internlink_employer.security import ReferenceTokenService

auth = ReferenceTokenService(secret)
token = auth.issue_token(user_id=1, role="employer")
```

## API

All endpoints are `POST` with a JSON object. Authenticated endpoints expect
`Authorization: Bearer <token>`.

Public:

| Endpoint | Purpose |
| --- | --- |
| `/api/employer/register` | create company + employer user, send verification email |
| `/api/employer/verify-email` | consume a verification token (`{"token": "..."}`) |

Authenticated actions (same names as the design's dispatch table):

`get_company`, `update_company`, `create_listing`, `update_listing`,
`set_listing_status`, `my_listings`, `listing_detail`, `applicants`,
`view_applicant`, `download_cv`, `decide`, `bulk_decide`, `send_message`,
`get_thread`, `inbox`, `my_placements`, `complete_placement`, `dashboard`,
`notifications`, `mark_notification_read`.

Success envelope:

```json
{"ok": true, "data": {}}
```

Failure envelope:

```json
{"ok": false, "category": "invalid", "message": "...", "fields": {"slots": "1 to 500"}}
```

Categories map to HTTP: `invalid` 400, `unauthenticated` 401, `forbidden` 403,
`not_found` 404, `conflict` 409, `server` 500.

`download_cv` returns the raw file bytes (`application/octet-stream`) after the
business ownership checks; all other actions return JSON.

## Integration points

### Auth module (4.2.1)

`AppContext.auth` only needs a `verify_token(token) -> dict | None` method; the
returned claims must include the integer `user_id`. `open_session` reads the
user row from the database and always takes `company_id` from the database,
never from the token or request body. The included HMAC token service is a
development/reference implementation.

### Database

`AppContext.db` implements the small `Database` contract in `db/base.py`.
`SQLiteDatabase` is used by tests and local development. `MySQLDatabase` uses
PyMySQL (`pip install -r requirements-mysql.txt`) and the tables/views in
`schema/schema.mysql.sql`. It requires MySQL 8.0.16+ so CHECK constraints are
enforced, and it stores naive timestamps in UTC.

```python
from internlink_employer.db import MySQLDatabase

db = MySQLDatabase(
    host="127.0.0.1",
    port=3306,
    user="internlink",
    password="...",
    database="internlink",
    init_schema=True,  # or run schema/schema.mysql.sql through your migration tool
)
```

The adapter sets the session variable `@internlink_actor_user_id` for each
write, so triggers or audit rules can see the acting user. It translates MySQL
duplicate-key, foreign-key, CHECK and NOT NULL errors into the module's
`DatabaseIntegrityError` categories.

Shared tables expected by other modules: `companies`, `users`, `auth_tokens`,
`listings`, `applications`, `placements`, `messages`, `notifications`,
`student_profiles`, `student_skills`, `student_interests`, plus the
`v_employer_applicants` view. Review the schemas against the shared project
schema before deploying.

The service layer applies the cross-module side effects explicitly inside the
same transaction:

- audit rows (`audit_log`)
- in-app notifications (`notifications`)
- a pending placement when an application is accepted (SR13 queue)
- `listings.slots_filled` recalculation

If the shared database already implements these through triggers, keep the
effect in one layer only to avoid duplicates. If another module cancels or
deletes a placement, it must free the slot as well (`recount_slots` implements
the same pending+confirmed rule) so `listings.slots_filled` cannot go stale.

### Other ports

- `Mailer.send(to, subject, body)` - registration verification email
- `Notifier.notify(user_id, type, title, message, related_type, related_id)` -
  deadline reminders; in-app notifications are written directly to the table
- `Storage.read_bytes(path)` - private CV storage; `LocalFileStorage` enforces
  path containment
- `MatchingCache.invalidate_all()` - called after listing changes so the
  recommendation cache (4.6) cannot serve stale data

## Key rules

- Listing drafts may be created by pending companies; publishing (`open`) needs
  a verified company and a deadline of today or later (SR07/SR08).
- Listing transitions: `draft -> open|hidden`, `open -> closed|hidden`,
  `closed -> open|hidden`, `hidden -> open|closed`.
- Application transitions (employer side): `submitted -> under_review|shortlisted|rejected`,
  `under_review -> shortlisted|rejected`, `shortlisted -> accepted|rejected`.
- Accepting an application checks capacity and creates a pending placement.
  Pending and confirmed placements occupy a slot; completing a placement frees it.
- Messaging is only allowed for shortlisted or accepted applications (SR10).
- Placement completion requires a confirmed placement, a passed end date and a
  performance note (SR11).
- All listing/application/placement lookups are scoped by the session company;
  another company's record returns `not_found` rather than leaking existence (SR17/NFR06).

## Security notes

- Parameterised SQL everywhere; the only dynamically interpolated SQL is the
  applicant sort column from a fixed whitelist.
- Passwords use PBKDF2-HMAC-SHA256 (600,000 iterations) with a per-password
  salt instead of bcrypt, because the core must stay stdlib-only.
- Verification tokens are random 256-bit values and only their SHA-256 hash is
  stored; bearer tokens use HMAC-SHA256 with constant-time comparison.
- Applicant profiles omit email, phone, student number and other contact data.
- CV access is authorised before reading and the storage adapter blocks path
  traversal.
- API responses use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
- Rate limiting, TLS, CORS and account lockout belong at the gateway/Auth module.

## Tests

The suite covers schema/transaction behaviour, integrity-error translation,
password/token security, registration and verification, sessions, company
profiles, listing validation/lifecycle/search/pagination, the daily job,
applicant review and privacy, CV authorisation, the full decision state machine
and capacity checks, bulk decisions, messaging/read receipts/inbox scoping,
placement completion and slot recalculation, dashboard counts, notifications,
WSGI routing/error mapping/binary responses, and storage path containment.

Run:

```powershell
python -m unittest discover -s tests -v
```

## Production checklist

1. Replace the reference token service with the real Auth module.
2. Use `MySQLDatabase` and run `schema/schema.mysql.sql` (or the shared project
   migrations); confirm the trigger/effect split described above.
3. Provide an SMTP/email `Mailer`, the notifications `Notifier`, private object
   `Storage` and the real matching cache.
4. Set `INTERNLINK_TOKEN_SECRET`, serve behind HTTPS, add rate limiting, and
   forward structured logs/audit events to the platform logger.
5. Schedule `daily_listing_job` once per day (cron/worker) with the shared
   notifier instance.
