# InternLink Uganda

InternLink is an internship placement platform for students, employers,
university coordinators and administrators. This repository deploys the React
application and Python API together on Vercel, using one shared PostgreSQL
database for accounts, opportunities, applications, placements, notifications
and audit records.

## Features

### Accounts (all roles)

- One sign-up screen: choose student, employer or university.
- Universities register themselves; the person who registers becomes the
  first coordinator, active once an administrator verifies the university.
- Resend the confirmation email, and reset a forgotten password by email.

### Student

- University email registration and email verification.
- Profile, skills, interests and location preferences.
- Searchable opportunities with sector, location and duration filters.
- Personalised recommendations from the PostgreSQL matching functions.
- Application submission, withdrawal, status tracking and notifications.
- Applications require a coordinator-verified student profile.

### Employer

- Employer/company registration and email verification.
- Company profile and verification status.
- Create, edit, publish, close and manage internship listings.
- Applicant review, shortlist/reject decisions and placement management.
- Shortlist-only messaging, notifications and dashboard data.

### University coordinator

- University-scoped student records and placement dashboard.
- Verify student profiles and approve or reject pending placements.

### Administrator

- Review and verify/reject company and university registrations.
- View user accounts, suspend/activate eligible accounts and inspect the
  append-only audit log.

Every dashboard reads and writes through the API. There is no local sample-data
or preview mode. The account menu in the top-right corner allows the signed-in
user to switch accounts or log out.

## Deploy to Vercel

### 1. Provision PostgreSQL

Create a persistent PostgreSQL 16 database with network access from Vercel.
Vercel's filesystem and function memory are not a persistent database. Use the
TLS-enabled connection string supplied by the database provider and plan for
the provider's connection limits.

Run the schema scripts against the new database, in this order:

1. `01_schema.sql`
2. `02_functions_triggers.sql`
3. `03_views_functions.sql`
4. `04_roles.sql` if using the database roles defined by the project.
5. `08_university_requests.sql` (students asking for a university that isn't listed yet)
6. `09_interviews_saved.sql` (interview stage, decline reasons, saved internships)
7. `10_cv_alerts_invites.sql` (CV uploads, job alerts, coordinator invites)
8. `11_companies_logos.sql` (company logos, "suggest a company")

Job alerts run once a day through a Vercel cron job (`vercel.json`), which calls
`/api/cron/job-alerts`. Set a `CRON_SECRET` environment variable in Vercel
(any long random string); Vercel sends it with each cron call and the endpoint
refuses calls without it. Alerts and coordinator invites send email, so they
also need email settings (Gmail or Resend, see below).

CVs are stored in the database (table `student_cvs`, at most 4 MB each because
Vercel limits uploads to 4.5 MB), so no separate file storage is needed.

Do **not** run `05_seed.sql` on a production database. It contains fixed demo
accounts and sample records. `06_tests.sql` and `07_load_test.sql` are
validation tools, not deployment migrations. The bootstrap process below
creates the minimum usable production records instead.

### 2. Configure Vercel environment variables

In **Vercel Project → Settings → Environment Variables**, set the values for
Production, Preview and Development as appropriate:

| Variable | Required | Purpose |
|---|---:|---|
| `INTERNLINK_DSN` | Yes | PostgreSQL connection string for the shared application database. Use the provider's TLS-enabled connection string. |
| `INTERNLINK_JWT_SECRET` | Yes | At least 32 random characters; signs access tokens for all roles. |
| `SMTP_USER` | For email (Gmail option) | The Gmail address that sends InternLink's emails. |
| `SMTP_PASSWORD` | For email (Gmail option) | A Gmail **app password** for that account (not its normal password). |
| `SMTP_HOST` / `SMTP_PORT` | Optional | Another SMTP server. Defaults to `smtp.gmail.com` and `587`. |
| `RESEND_API_KEY` | For email (Resend option) | Resend API key. Used only when the Gmail settings are not set. |
| `INTERNLINK_FROM_EMAIL` | For Resend; optional for Gmail | Sender address. Must be verified in Resend. With Gmail it defaults to `SMTP_USER`. |
| `INTERNLINK_PUBLIC_BASE_URL` | Recommended | Public site address used in email links, for example `https://internlink.vercel.app`. Without it, links point at the deployment's own URL, which may be behind Vercel's login. |
| `INTERNLINK_CV_ROOT` | Optional/local only | Private local CV directory. Vercel's filesystem is not durable storage. |

Sign-up, password reset, job alerts and coordinator invites all send email, so
one of the two email options must be set up. **Gmail is the quickest** and needs
no domain:

1. Sign in to the Gmail account that will send the emails (a team account such
   as `internlink.team@gmail.com` is best).
2. Turn on 2-Step Verification at <https://myaccount.google.com/security>.
3. Create an app password at <https://myaccount.google.com/apppasswords>
   (name it "InternLink"). Google shows 16 letters.
4. In Vercel, set `SMTP_USER` to the Gmail address and `SMTP_PASSWORD` to the
   16 letters (spaces are fine), set `INTERNLINK_PUBLIC_BASE_URL`, and redeploy.

Gmail allows about 500 emails a day, which is plenty for a pilot. For more, use
Resend with a verified domain instead.

Generate a signing secret locally instead of reusing a checked-in or example
value:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Add it to Vercel as `INTERNLINK_JWT_SECRET`. Never put database credentials,
JWT secrets or provider keys in source files or `VITE_*` variables.

### 3. Deploy

The root `vercel.json` installs and builds the React app from `frontend/`,
serves `frontend/dist` as the SPA, and routes `/api/*` to
[`api/index.py`](api/index.py). Connect the Git repository in Vercel or deploy
with the CLI:

```powershell
npm install --global vercel
vercel
vercel --prod
```

Check `/api/health` after deployment. This endpoint confirms that the Python
function is responding; it does not by itself prove the database or email
provider is configured.

### 4. Create initial accounts and usable sample data

After applying the schema and setting up `INTERNLINK_DSN`, run the bootstrap
script once from the repository root in an environment that can reach the
database:

```powershell
python -m pip install -r requirements.txt
$env:INTERNLINK_DSN = "<your PostgreSQL connection string>"
python scripts\seed_initial_accounts.py
```

It provisions one administrator, one verified university and coordinator,
one verified student profile, one verified employer/company, one open
internship and the skills needed for recommendations. Passwords are generated
independently using a cryptographically secure random generator, stored as
bcrypt hashes, and printed only for accounts created by that run. Save the
output in a password manager; the script cannot recover a password later.

The account email addresses are:

| Role | Sign-in email |
|---|---|
| Administrator | `admin@internlink.ug` |
| University coordinator | `coordinator@must.ac.ug` |
| Student | `student@std.must.ac.ug` |
| Employer | `employer@internlink.example` |

There are no shared or hard-coded default passwords. If a matching bootstrap
account already exists and is active, its password is retained and is not
printed again. To deliberately rotate the existing bootstrap passwords and
print the new credentials, run:

```powershell
python scripts\seed_initial_accounts.py --rotate-existing
```

Rotating resets those accounts to active and verified. Do not run that option
as part of routine deployments.

## API overview

All authenticated endpoints require `Authorization: Bearer <access_token>`.
Tokens are issued by `POST /api/v1/auth/login` for student, employer,
coordinator and administrator accounts.

### Student and public endpoints

- `POST /api/v1/auth/register`, `/api/v1/auth/login`,
  `/api/v1/auth/verify-email` (students and coordinators)
- `POST /api/v1/auth/register-university` creates a pending university and
  its first coordinator
- `POST /api/v1/auth/resend-verification`, `/api/v1/auth/forgot-password`
  always answer `202` with the same message, so they don't reveal which
  emails have accounts
- `POST /api/v1/auth/reset-password` with `token` and `password`
- `GET /api/v1/public/universities`, `/api/v1/public/catalogs`
- `GET /api/v1/public/universities/{id}/departments`
- `GET /api/v1/public/departments/{id}/programmes`
- `GET /api/v1/public/universities/{id}/programmes`: every programme with its department, for sign-up
- `GET /api/v1/public/home`: latest internships, partner universities and locations
- `GET /api/v1/public/opportunities` with `q`, `location`, `sector`, `remote`, `min_weeks`,
  `max_weeks`, `closing_soon`, `my_programme`, `sort` (`closing` or `newest`) and `page`;
  returns sector counts for the filter panel
- `GET /api/v1/public/opportunities/{id}`: internship details. With a student token it also
  returns the match score breakdown and the student's application
- `POST /api/v1/public/university-requests` with `university_name`, `requester_email` and
  optional `coordinator_email`
- `GET`, `PUT /api/v1/students/me/profile`
- `GET /api/v1/opportunities` with search and filter parameters
- `GET /api/v1/students/me/recommendations`
- `GET`, `POST /api/v1/students/me/applications`
- `POST /api/v1/students/me/applications/{id}/withdraw`
- `GET /api/v1/students/me/saved`, `PUT` and `DELETE /api/v1/students/me/saved/{listing_id}`
- `GET`, `PUT`, `DELETE /api/v1/students/me/cv`: CV details, upload (the file itself as
  the request body, `?filename=` for its name; PDF or DOCX, at most 4 MB) and removal;
  `GET /api/v1/students/me/cv/file` downloads it
- `GET`, `POST /api/v1/students/me/alerts` (`{"filters": {...}}` with the search page's
  `q`, `location`, `sector`, `remote`, `duration`, `my_programme`) and
  `DELETE /api/v1/students/me/alerts/{id}`
- `GET /api/v1/public/companies` with `q`, `sector` and `page`: verified companies, including
  those with no open internships; `GET /api/v1/public/companies/{id}` for one company and its
  open internships; `GET /api/v1/public/companies/{id}/logo` for its logo image
- `POST /api/v1/public/company-requests` with `company_name`, optional `website` and
  `requester_email`: a student suggests a company that isn't on InternLink
- `GET`, `PUT`, `DELETE /api/v1/employer/logo` (employer token; `PUT` sends the image itself,
  PNG, JPEG or WebP up to 1 MB) and `GET /api/v1/employer/logo/file` to preview it
- `GET /api/v1/auth/invite?token=` and `POST /api/v1/auth/accept-invite` with `token`,
  `full_name` and `password`: the page a coordinator invite email links to
- `GET`, `POST /api/v1/students/me/applications/{id}/messages`: read the employer's
  messages and reply (only after the employer has written, while shortlisted or accepted)
- `GET /api/v1/students/me/notifications`
- `POST /api/v1/students/me/notifications/{id}/read`

### Administrator endpoints

- `GET /api/v1/admin/registrations`, `/api/v1/admin/users`,
  `/api/v1/admin/audit`
- `GET /api/v1/admin/registrations/{company|university}/{id}`: details for review
- `POST /api/v1/admin/registrations/{company|university}/{id}`
- `GET /api/v1/admin/universities`: verified universities with coordinator counts
- `GET /api/v1/admin/company-requests`; `POST` with `company_name` and `status`
  (`invited` or `declined`) closes the open suggestions for that company
- `GET /api/v1/admin/universities/{id}/coordinators`; `POST` with `email` and optional
  `department_id` invites a coordinator by email
- `GET /api/v1/admin/university-requests`; `POST` with `university_name` and
  `status` (`added` or `declined`) closes the open requests for that university
- `PATCH /api/v1/admin/users/{id}`

### University coordinator endpoints

- `GET /api/v1/coordinator/dashboard`, `/students`, `/placements`
- `POST /api/v1/coordinator/students/{id}`
- `GET /api/v1/coordinator/coordinators`; `POST` with `email` and optional `department_id`
  (university-wide coordinators only) invites a colleague
- `POST /api/v1/coordinator/placements/{id}` with `action` (`confirmed` or `rejected`),
  `reason` (required to reject) and optional `start_date`; the end date follows from
  the internship's length

### Employer endpoints

Employer registration and verification use `POST /api/employer/register` and
`POST /api/employer/verify-email`. Authenticated employer operations are
available as `POST /api/employer/{action}`; actions include `dashboard`,
`get_company`, `update_company`, `create_listing`, `update_listing`,
`set_listing_status`, `my_listings`, `applicants`, `view_applicant`, `decide`
(`shortlist`, `interview` with `interview_at`, `accept`, `reject` with optional `reason`),
`send_message`, `get_thread`, `inbox`, `my_placements`,
`complete_placement`, `notifications` and `mark_notification_read`.

The employer service contract and request details are in the
[employer module README](employer_module/README.md).

## Production limitations and security notes

- CV upload is not implemented. CV download uses a local-file adapter and is
  not a durable or supported Vercel upload solution. Add private object storage
  before using CVs in production.
- Verification email delivery requires a configured Resend sender and API key.
  Registration reports provider or configuration errors instead of claiming
  that an email was sent.
- The bootstrap employer email uses the reserved `.example` domain and is for
  initial platform setup, not email delivery. Change the account email through
  an appropriate account-management process before relying on employer
  correspondence.
- The bootstrap utility is designed for an empty, migrated application
  database. Do not import `05_seed.sql` into the production database.
- Hosted Vercel/database behavior can only be verified after configuring the
  deployment secrets and a reachable PostgreSQL service.

## Local development

Install the Python dependencies and create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Install and start the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

In another terminal, configure the local API environment and run Vercel's
function emulator from the repository root:

```powershell
$env:INTERNLINK_DSN = "postgresql://postgres@localhost:5432/internlink"
$env:INTERNLINK_JWT_SECRET = "<a random secret of at least 32 characters>"
$env:SMTP_USER = "<Gmail address>"
$env:SMTP_PASSWORD = "<Gmail app password>"
vercel dev --listen 3000
```

Vite's development proxy forwards `/api/*` requests to `http://127.0.0.1:3000`.
Apply the SQL migrations and bootstrap an account before signing in. Student
registration sends an email and therefore needs working email settings (Gmail
or Resend).

## Tests and validation

Build and test the React frontend:

```powershell
npm --prefix frontend run build
npm --prefix frontend test
```

Run Python tests from the repository root:

```powershell
pytest
```

PostgreSQL integration tests require `INTERNLINK_TEST_DSN` and a database
initialized with the required schema; otherwise those tests are skipped.
Employer unit tests use SQLite and do not require a separate production
database:

```powershell
Set-Location employer_module
python -m unittest discover -s tests -v
```

## Repository map

```text
api/index.py                         Shared Vercel Python API
vercel.json                          Vercel build and route configuration
frontend/                            React + TypeScript application
student_module/                      Student authentication, profile and applications
matching_engine/                     Recommendations and matching service
employer_module/internlink_employer/ Employer APIs and PostgreSQL adapter
scripts/seed_initial_accounts.py     Secure one-time account bootstrap
01_schema.sql ... 04_roles.sql       Shared PostgreSQL schema and routines
docs/                                Design, testing and results
```

## License

See [LICENSE](LICENSE).
