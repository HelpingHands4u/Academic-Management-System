# Brainware University Academic Management Portal

Backend for role-based academic administration, implemented through Phases 1-12.
The existing frontend is maintained separately and has not been integrated by this
backend work. No official university grading scale or academic dataset is bundled.

## Stack

- Python
- FastAPI
- Firebase Authentication
- Firebase Admin SDK
- Cloud Firestore
- REST API
- Vercel deployment

## Architecture and Modules

`/api/v1/ routers -> Pydantic schemas -> services -> Firebase Admin SDK / Cloud Firestore`

Firebase Authentication owns login identities; `users/{uid}` holds trusted portal
profiles and roles. Firestore is the only application database. ADMIN manages
academic definitions and accounts; FACULTY sees assigned offerings and permitted
academic records; STUDENT sees personal academic data and published results.
Authorization is enforced by backend dependencies and service-level scope checks.

```text
backend/
  api/index.py          Vercel ASGI entrypoint
  app/main.py           App factory, CORS, safe errors, router registration
  app/core/             Settings, Firebase initialization, auth, domain errors
  app/routers/          Thin /api/v1/ endpoints
  app/schemas/          Pydantic request and response contracts
  app/services/         Academic logic, queries, calculations, audit
  scripts/              Admin bootstrap and optional Firebase connectivity check
  tests/                Isolated tests with mocked Auth and Firestore
  .env.example          Empty credential placeholders and configurable windows
  .python-version       Python 3.13 (matches the local validation runtime)
  .gitignore            Git exclusions
  .vercelignore         Deployment upload exclusions
  requirements.txt      Existing compatible dependency ranges
  vercel.json           Python build and routing configuration
```

| Module | API prefixes under `/api/v1` | Stored collections |
| --- | --- | --- |
| Identity | `auth`, `users`, `students`, `faculty` | `users`, `students`, `faculty` |
| Academic structure | `departments`, `programs`, `academic-sessions`, `semesters` | `departments`, `programs`, `academic_sessions`, `semesters` |
| Teaching | `courses`, `course-offerings`, `enrollments`, `attendance` | `courses`, `course_offerings`, `enrollments`, `attendance` |
| Assessment | `examinations`, `exam-schedules`, `marks`, `results`, `grading-scheme` | `examinations`, `exam_schedules`, `marks`, `results`, `settings/grading_scheme` |
| Communication | `timetable`, `notices` | `timetable`, `notices` |
| Operations | `reports`, `analytics`, `audit-logs`, `sessions` | Existing academic data, `audit_logs`, `user_sessions` |

Reports and analytics use actual stored data. Attendance, SGPA and CGPA calculations
are performed by services, not accepted from clients. Sessions require explicit
start/heartbeat/logout requests; no simulated online counters are used. GROQ is
reserved configuration only; no chatbot is implemented.

Detailed module endpoints and rules are retained in the phase reference sections below.

## Local Run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# First setup only; do not overwrite an existing configured .env.
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

Run these commands from `backend/`. On POSIX use `source .venv/bin/activate`.
Supply the environment values locally before exercising protected endpoints.
The basic health endpoint and documentation work without Firebase credentials.

## Environment and Firebase Setup

| Variable | Purpose |
| --- | --- |
| `FIREBASE_PROJECT_ID` | Target Firebase project ID |
| `FIREBASE_CLIENT_EMAIL` | Server service-account email |
| `FIREBASE_PRIVATE_KEY` | Server service-account private key |
| `FRONTEND_URL` | Allowed HTTP(S) origin, such as `http://localhost:5500`; comma-separated origins supported |
| `GROQ_API_KEY` | Optional server-only placeholder for future use |
| `SESSION_ACTIVE_WINDOW_SECONDS` | Open-session activity window, default 300 |
| `SESSION_RECENT_WINDOW_SECONDS` | Recent activity window, default 86400 |

Keep the recent window at least as long as the active window. `.env.example`
contains no live credentials. Settings accept UTF-8 files with or without a BOM.
`FIREBASE_PRIVATE_KEY` accepts actual newlines or literal `\n` sequences; these
are normalized before creating the Firebase certificate. Surrounding quotes
are stripped. Never paste a real key into source, README, logs, screenshots or Git.
`GROQ_API_KEY` and the Firebase private key are excluded from settings serialization
and repr; no API returns the settings object.

1. Select the intended Firebase project and enable the required Authentication
   sign-in provider (email/password for the existing account creation workflow).
2. Create the Cloud Firestore database used by the default Admin SDK client.
3. Configure a service account with the Auth user-management and Firestore
   permissions needed by these APIs. Keep credentials in local `.env` or the
   deployment provider's environment settings.
4. Provision the first administrator with `python -m scripts.bootstrap_admin`
   as described below. This command creates a real account; do not run it as a
   connectivity test. Later accounts are provisioned by authenticated ADMIN APIs.
5. Deny direct browser access to portal collections unless separately reviewed.
   The Admin SDK bypasses client Firestore rules and uses IAM; backend role and
   ownership checks remain essential. See [Firebase's security guidance](https://firebase.google.com/docs/firestore/security/overview).

Firebase initialization is lazy, locked and reuses the default app within each
worker. Firestore access goes through `get_firestore_client()`. Multiple serverless
workers initialize independently; no academic state is held only in process memory.

### Optional Real Connectivity Check

After reviewing the target project, explicitly run:

```powershell
python -m scripts.verify_firebase --read-only --expected-project YOUR_PROJECT_ID
```

This performs at most one Auth user-page read and one Firestore `users` document
read. It prints only success/failure, never users, tokens or exception text, and
writes nothing. Successful execution validates those reads only: it does not prove
all composite indexes, mutation permissions, grading rules or deployment behavior.
The Phase 12 automated checks mock Firebase; real connectivity is not claimed.

## API and Frontend Integration

Swagger: `/docs`; ReDoc: `/redoc`; generated API schema: `/openapi.json`.
The **Authorize** button accepts a Firebase ID token using the `FirebaseBearer`
security scheme. Health is public and returns exactly:

```json
{"status":"ok","service":"Brainware University Academic Management Portal"}
```

The frontend must sign in through Firebase Authentication, obtain a current ID
token, then send `Authorization: Bearer <Firebase ID token>` on protected requests.
Send JSON bodies with `Content-Type: application/json`; follow the generated schemas.
An ID token is not an Admin SDK credential or a Firebase custom token.
Do not put tokens in query strings, analytics metadata or logs.

The backend verifies token signature, expiry, revocation and disabled-account state.
It also checks the portal profile. Contradictory role claims and profiles return
403 until the client refreshes its token (`getIdToken(true)`) or signs in again;
malformed stored profiles fail closed. See [Firebase session verification](https://firebase.google.com/docs/auth/admin/manage-sessions).

Existing response contracts are preserved:

- Single-resource endpoints return a JSON object; creation generally returns 201.
- Paginated collections use `{"items": [...], "next_cursor": null}` with `limit`
  (maximum 100) and `cursor`. Pass back `next_cursor` with unchanged filters.
- Reports add a `summary` object. Summary/analytics/self-service endpoints may
  use their own response schemas; do not assume every endpoint is a paginated list.
- Domain errors use `{"detail": "safe message"}`. Validation returns 422 with a
  `detail` array containing `loc`, `msg` and `type`, without echoed request inputs.
- 400 means invalid business input, 401 missing/invalid credentials, 403 denied,
  404 missing or hidden out-of-scope records, 409 conflict, 422 invalid fields,
  500 unexpected internal failure, and 503 unconfigured/unavailable auth/profile
  service. Do not retry mutations blindly after an ambiguous failure.
- `/api/` responses have `Cache-Control: no-store` to avoid caching personal data.

Use the configured backend base URL, not relative paths to a frontend-only host.
`FRONTEND_URL` must contain origins only (scheme, host and optional port), not
paths, credentials or wildcard subdomains. `*` is excluded. No origin configured
means cross-origin browser access is not enabled. CORS allows the configured
development origin and applies to safe error responses as well as successful ones.
CORS does not replace authentication.

Students cannot widen academic scope by submitting another UID or student ID.
Administrative account/profile creation legitimately accepts target identifiers;
self-service endpoints derive identity from the authenticated caller. Faculty
permissions remain limited to assigned offerings. No frontend file or API call
has been added by this phase.

## Testing and Deployment

```powershell
python -m compileall -q app api scripts tests
python -m pip check
python -m pytest -q
python -c "from api.index import app; assert app.openapi()['paths']['/api/v1/health']"
python -m uvicorn api.index:app --host 127.0.0.1 --port 8123
```

Then check `/api/v1/health`, `/docs`, `/redoc`, `/openapi.json`, and that
`/api/v1/auth/me` and `/api/v1/users/me` return 401 without a token.
Tests use mocks/fakes and do not require or mutate production Firebase data.
Requirements were reviewed without upgrading packages: pytest/httpx support the
tests; python-dotenv supports settings; email-validator supports email schemas.
The existing dependency ranges remain, so a fresh installation must pass the
suite before release. No vulnerability-free claim is implied by `pip check`.

For Vercel, select **backend** as the project root. Keep `api/index.py` as the ASGI
entrypoint and the existing `vercel.json` Python build/catch-all route. Set the
server environment variables separately for Preview and Production, with the
appropriate frontend origin for each environment. `.python-version` selects
Python 3.13; `.vercelignore` excludes local environments, credentials and tests
from CLI uploads. Vercel supports ASGI apps and explicit Python versions;
see the [Python runtime documentation](https://vercel.com/docs/functions/runtimes/python).
Validate the deployed health/auth/docs endpoints and browser CORS after deployment.
Local import/startup checks are not a Vercel deployment validation.

## GitHub Security and Review

`.gitignore` excludes `.env`, `.env.*` (except `.env.example`), known service-account
JSON naming patterns, private-key files, virtual environments, caches, coverage,
IDE and temporary files. Other JSON such as `vercel.json` remains usable.
Keep arbitrarily named credentials under ignored `secrets/` or outside the project;
never solve this by ignoring all JSON. Ignore rules do not remove already tracked
secrets. Before committing, inspect `git status --short`, `git diff --check`,
`git diff --cached --stat` and `git check-ignore .env`; review staged files privately.
If a credential was previously committed, remove it from tracking/history and
rotate it. Never publish a real `.env` for a university demonstration.

This working directory has no Git repository, so Phase 12 cannot verify tracked
files or repository history. Ignore patterns are tested in an isolated temporary
repository, and frontend file hashes are compared before/after local work.

## Readiness Limits

- Real Firebase reads, write permissions, index creation and deployed Vercel
  behavior require an explicit environment validation. None is inferred from
  passing mock tests or from the existence of a local `.env`.
- Composite indexes depend on actual filter combinations. Range queries order
  first by the range field; verify `user_sessions` activity ranges, audit timestamp
  ranges, attendance date ranges and multi-filter academic queries against the
  target database. No speculative index configuration is supplied. Client error
  responses deliberately hide provider details; use a trusted local administrative
  query or the Firebase console for index diagnostics.
- Existing conflict checks use read-then-write queries; simultaneous scheduling
  requests can race. Result regeneration and cross-service Auth/profile changes
  are not distributed transactions. Failed recalculation now blocks publication,
  but mark-triggered regeneration remains best-effort: regenerate affected results
  after a failure and serialize administrative changes during demonstrations.
  Load/concurrency hardening is still required before high-volume academic use.
- Reports/feeds are bounded scans where aggregation cannot be pushed to Firestore.
  Narrow filters when scan caps are reached. Audit writes are best-effort and
  failed writes log only the exception type; this is not an immutable compliance log.
- Metadata sanitization removes credential-like keys recursively, including nested
  lists, camelCase and hyphenated forms. Do not place secrets in free-text values.
- The university/project owner must supply and approve official grading settings
  before production academic use. No academic data is generated by setup scripts.

For a viva, demonstrate the architecture, generated Swagger contracts, role denials,
deterministic attendance/grade calculations, publication controls and test suite.
Use only owner-approved records in an approved demonstration project.

### Phase 12 Local Verification

`.venv\Scripts\python -m pytest -q`: **369 passed, 14 warnings in 33.90s**.
All 349 pre-existing tests remain unchanged and passing; 20 focused hardening
checks were added. Warnings are the existing Starlette/httpx and HTTP 422 constant
deprecations. Syntax/import checks and `pip check` passed. Startup through
`api.index:app` with Firebase credentials disabled returned 200 for health, docs,
ReDoc and OpenAPI, and 401 for unauthenticated auth/user self-service requests.
All 107 API operations are represented in OpenAPI; protected operations declare
bearer security and reject anonymous calls. All 25 frontend files retained their
original SHA-256 hashes. No real Firebase check, Vercel deployment or GitHub push
was performed in Phase 12.

## Phase 2: Firebase Authentication Foundation

### Architecture

The frontend signs users in with Firebase Authentication and obtains a Firebase ID token. It sends the token to this API on every request:

```
Authorization: Bearer <Firebase ID token>
```

The backend verifies the token server-side with the Firebase Admin SDK (`app/core/firebase.py`, `app/core/security.py`). Invalid, expired, or missing tokens return `401`. If Firebase credentials are not configured, protected endpoints return `503`; the app itself still starts and `/api/v1/health` works.

### Firestore `users/{uid}` profile

Each portal user has a document `users/{uid}` (the Firebase Auth uid) with fields: `uid`, `email`, `display_name`, `role`, `student_id`, `faculty_id`, `department_id`, `program_id`, `semester_id`, `is_active`, `created_at`, `updated_at`. Academic fields are optional until later phases. Profiles are never auto-created; `GET /api/v1/auth/me` reports `profile_provisioned: false` when none exists. Schema: `app/schemas/user.py`; access layer: `app/services/users.py`.

### Role-based authorization

Roles: `ADMIN`, `FACULTY`, `STUDENT`. The role is resolved only from trusted sources: the Firebase custom claim `role` first, then `users/{uid}.role` in Firestore. Contradictory claims and profiles are denied with `403`; malformed profiles fail closed with `503`. Roles sent by the client (body, query, headers) are never trusted. Disabled profiles (`is_active: false`) get `403`.

Reusable dependencies in `app/core/security.py`: `get_firebase_user`, `get_current_uid`, `get_auth_context`, `require_admin()`, `require_faculty()`, `require_student()`, `require_roles(...)`. Usage: `Depends(require_admin())`. Unauthenticated gives `401`; insufficient role gives `403`.

### Endpoints

- `GET /api/v1/health`
- `GET /api/v1/auth/me` (requires Bearer token)

### Environment variables

`FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY` (escaped `\n` sequences are handled), `FRONTEND_URL` (comma-separated allowed CORS origins), `GROQ_API_KEY` (optional; not needed until the chatbot phase). Copy `.env.example` to `.env` and fill it in.

### Local setup

```powershell
pip install -r requirements.txt
copy .env.example .env   # then fill in your values
uvicorn app.main:app --reload
pytest
```

> **Warning:** You must supply your own real Firebase credentials (from a service account in your Firebase project). None are included. Never commit `.env` or service-account JSON files. Tests use mocks and do not contact Firebase; real Firebase authentication has not been verified by this repository.


## Phase 3: User Provisioning & Role Management

### Architecture

`routers -> schemas -> services -> Firebase/Firestore layer`

- `app/routers/users.py`: HTTP only (maps domain errors to 400/404/409/500/503).
- `app/schemas/user.py`: Pydantic validation (`UserCreate`, `UserProfile`, `UserListResponse`).
- `app/services/users.py`: user business logic; `app/services/audit.py`: audit abstraction.
- `app/core/firebase.py`: Admin SDK wrappers (create/delete Auth user, custom claims); `app/core/security.py`: auth dependencies; `app/core/errors.py`: domain errors.

### Roles and Firestore `users/{uid}`

Roles: `ADMIN`, `FACULTY`, `STUDENT`. Document id = Firebase Auth uid. Fields: `uid`, `email`, `display_name`, `role`, `student_id`, `faculty_id`, `department_id`, `program_id`, `semester_id`, `is_active`, `created_at`, `updated_at` (UTC timestamps). Passwords and ID tokens are never stored. STUDENT requires `student_id`; FACULTY requires `faculty_id`.

### User creation flow (`POST /api/v1/users`, ADMIN only)

1. Token verified, role resolved server-side, request validated (email, role, password: 8-128 chars with upper, lower and digit; IDs `[A-Za-z0-9._-]{1,64}`).
2. Firebase Auth user created (duplicate email -> `409`).
3. Custom claim `role` set, then `users/{uid}` created (never overwrites).
4. If step 3 fails the Auth user is deleted (rollback) and `500` is returned with no internal detail.
5. An audit event is written best-effort to `audit_logs`. The response is the safe profile; the password is never returned, stored or logged.

### Authentication and authorization flow

Bearer Firebase ID token -> verified by Admin SDK (`401` on failure) -> Firestore profile loaded -> `is_active: false` gives `403` -> role = custom claim `role`, else `users/{uid}.role` -> `require_admin()/require_faculty()/require_student()/require_roles()` give `403` if not permitted. `require_authenticated_user` needs only a valid, active identity. Client-supplied roles are ignored. Role/claim changes need the client to refresh its ID token (`getIdToken(true)`) or sign in again. Firestore is the application profile source; the claim is a mirror written at creation. Note: a deactivated profile is enforced via Firestore on every request, so it takes effect immediately.

### Endpoints

- `GET /api/v1/health`
- `GET /api/v1/auth/me` (any valid token; reports `profile_provisioned: false` if no profile)
- `POST /api/v1/users` (ADMIN)
- `GET /api/v1/users` (ADMIN; filters `role`, `is_active`, `department_id`; `limit` 1-100, `cursor`)
- `GET /api/v1/users/me` (any active user; 404 if no profile)
- `GET /api/v1/users/{uid}` (ADMIN)

Filtered list queries combined with ordering may require a composite Firestore index; Firestore returns a link in the server log if so.

### Admin bootstrap

There is no public admin-creation route and no default credentials. Create the first admin once, locally, with your real `.env` credentials:

```powershell
$env:BOOTSTRAP_ADMIN_PASSWORD = "<choose a strong password>"   # or omit to get a hidden prompt
python -m scripts.bootstrap_admin --email you@yourdomain.com --name "Your Name"
Remove-Item Env:BOOTSTRAP_ADMIN_PASSWORD
```

The script refuses to run if an ADMIN profile already exists. Afterwards the admin signs in via Firebase and uses `POST /api/v1/users`. Alternatively create the user in the Firebase console, set claim `role=ADMIN`, and add `users/{uid}` manually.

### Environment variables

Unchanged: `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`, `FRONTEND_URL`, `GROQ_API_KEY`. Optional for the script only: `BOOTSTRAP_ADMIN_PASSWORD`.

### Testing

```powershell
.venv\Scripts\python -m pytest -q
```

Tests use fakes and need no Firebase credentials.


## Phase 4: Academic Structure Foundation

No academic data is seeded and no official Brainware program list is assumed. All departments, programs, sessions and semesters are entered by an ADMIN through the API.

### Hierarchy and Firestore collections

```
departments/{id}  <-  programs/{id}  <-  semesters/{program__session__number}  ->  academic_sessions/{id}
```

- `departments/{id}`: `name`, `code`, `description`, `is_active`, `created_at`, `updated_at`. Document id = slug of `code`.
- `programs/{id}`: `name`, `code`, `department_id`, `degree_type`, `duration_years`, `total_semesters`, `is_active`, timestamps. Id = slug of `code`.
- `academic_sessions/{id}`: `name` (e.g. `2026-27`, entered by the admin), `start_date`, `end_date`, `is_current`, `is_active`, timestamps. Id = slug of `name`. Dates are stored as ISO `YYYY-MM-DD` strings.
- `semesters/{id}`: `program_id`, `academic_session_id`, `semester_number`, `name`, `start_date`, `end_date`, `is_current`, `is_active`, timestamps. Id = `{program_id}__{session_id}__{semester_number}`.

IDs are generated server-side from the unique business key and never taken from the client. Because Firestore `create()` fails on an existing id, uniqueness of codes, session names and program+session+semester number is enforced atomically (duplicates return `409`). `code`/`name` (and program/session/number for semesters) are immutable after creation.

### Endpoints

Each of `/api/v1/departments`, `/api/v1/programs`, `/api/v1/academic-sessions`, `/api/v1/semesters` supports `POST`, `GET` (list), `GET /{id}` and `PATCH /{id}`. There is no DELETE: records are deactivated with `PATCH {"is_active": false}`.

List filters: departments `is_active`; programs `department_id`, `is_active`; sessions `is_active`, `is_current`; semesters `program_id`, `academic_session_id`, `semester_number`, `is_active`, `is_current`. All lists support `limit` (1-100) and `cursor` (`next_cursor` from the previous page).

### Authorization

- Create/update/deactivate: ADMIN only (`403` otherwise, `401` without a valid token).
- Reads: any authenticated, active user with a portal role (ADMIN, FACULTY, STUDENT). Non-admins only see active records, regardless of the `is_active` filter; inactive records return `404` to them.
- Roles come from the verified token claim / Firestore profile, never from the request.

### Validation rules

- Department/program `code`: 2-20 chars (letters, digits, `_`, `-`), upper-cased. Duplicate gives `409`.
- Program: department must exist (`404`) and be active (`400`); `duration_years` 1-10, `total_semesters` 1-20 (`422`); `total_semesters` cannot drop below an existing semester number.
- Session: `start_date < end_date` (`422`); at most one current session (setting one current atomically clears the others); inactive sessions cannot be current (`400`).
- Semester: program and session must exist (`404`) and be active (`400`); `semester_number` 1-20 and not above the program's `total_semesters` (`400`); `start_date < end_date` (`422`); at most one current semester per program.
- Referential safety: a department with active programs and a program with active semesters cannot be deactivated (`409`). Referenced records are never deleted.
- The current-semester rule is per program, since each program has its own calendar; it is a design choice that can change later.

### Firestore indexes

Lists use equality filters and the default `__name__` order. Verify the chosen filter combinations against the target database; no composite indexes are predefined. Provider index diagnostics are hidden from API responses and must be inspected through trusted administrative tooling.

### Use by later modules

Courses, enrollments, attendance, exams, marks, timetables and notices will reference `department_id`, `program_id`, `academic_session_id` and `semester_id`. The `department_id`, `program_id` and `semester_id` fields on `users/{uid}` can now point to these records (they are not yet cross-validated at user creation).

### Tests

```powershell
.venv\Scripts\python -m pytest -q
```


## Phase 5: Courses & Course Offerings

No course data is seeded. Fields and the marks configuration are generic, configurable values entered by an ADMIN; they are not official Brainware University rules.

### Hierarchy

```
departments <- programs <- courses            (reusable definition)
                 |            ^
                 v            |
              semesters ->  course_offerings  (a course delivered in one semester + section)
                 |
                 v
          academic_sessions
```

A **course** is a reusable definition tied to one program (and that program's department) and a semester number. A **course offering** is that course delivered in a concrete `semester` (which fixes the program and academic session) for a `section`, optionally with a faculty member, room and capacity.

### Firestore collections

- `courses/{id}`: `code` (upper-cased, unique), `name`, `description`, `department_id`, `program_id`, `credits`, `course_type` (`CORE|ELECTIVE|PRACTICAL|PROJECT|OTHER`), `semester_number`, `max_marks`, `passing_marks`, `is_active`, timestamps. Id = slug of `code`.
- `course_offerings/{id}`: `course_id`, `academic_session_id`, `semester_id`, `program_id`, `department_id`, `section`, `faculty_uid`, `faculty_id`, `room`, `capacity`, `status` (`PLANNED|ACTIVE|COMPLETED|CANCELLED`), timestamps. Id = `{course_id}__{semester_id}__{section}`.

IDs are derived server-side, so Firestore `create()` enforces uniqueness (course code; course + semester + section) atomically and returns `409`. `program_id`, `department_id` and `academic_session_id` on an offering are derived from the stored semester/course; if a client supplies them they must match or the request is rejected. Immutable after creation: course code/department/program/semester number; offering course/semester/section.

### Endpoints

`POST|GET /api/v1/courses`, `GET|PATCH /api/v1/courses/{course_id}`, `POST|GET /api/v1/course-offerings`, `GET|PATCH /api/v1/course-offerings/{offering_id}`. No DELETE: deactivate a course with `is_active: false`; cancel an offering with `status: CANCELLED`.

Course filters: `department_id`, `program_id`, `semester_number`, `course_type`, `is_active`, `search` (course-code prefix). Offering filters: `course_id`, `academic_session_id`, `semester_id`, `program_id`, `department_id`, `faculty_uid`, `section`, `status`. Lists use the same `limit`/`cursor` pagination as earlier phases.

### Authorization

- Create/update: ADMIN only (`403` otherwise, `401` unauthenticated).
- Courses: ADMIN, FACULTY and STUDENT can read; non-admins only see active courses.
- Offerings: ADMIN sees all. FACULTY sees only offerings where `faculty_uid` is their own uid (other offerings return `404`; the `faculty_uid` filter is overridden). STUDENT sees offerings of the program (and semester, if set) on their own `users/{uid}` profile with status PLANNED/ACTIVE/COMPLETED; a student with no `program_id` sees none. Faculty cannot change ownership (updates are ADMIN-only).

### Faculty assignment

`faculty_uid` is optional. When given (create or PATCH), the backend checks that the Firebase Auth account exists and is not disabled, that `users/{uid}` has role `FACULTY`, and that the profile is active. Otherwise: `404` (unknown), `400` (wrong role or inactive). `faculty_id` is copied from the profile. `PATCH {"faculty_uid": null}` unassigns. There is no separate faculty collection yet.

### Validation rules

- Course: code and name required; credits > 0; semester_number > 0 and <= the program's `total_semesters`; max_marks > 0; 0 <= passing_marks <= max_marks (`422`); department and program must exist (`404`), be active, and the program must belong to the department (`400`).
- Offering: course, semester (and any supplied session/program/department) must exist (`404`); semester must belong to the supplied program/session, course must belong to the semester's program and department, and the course semester_number must equal the semester's number (`400`); course, semester, session and program must be active (`400`); `section` is 1-10 alphanumerics, upper-cased; `capacity` > 0.
- A course with PLANNED/ACTIVE offerings cannot be deactivated (`409`).

### Firestore indexes

Lists use equality filters, `in` on `status`, and the default `__name__` order. Combining several equality filters is served by Firestore's index merging, so no composite index is predefined. The course `search` uses a range on `code` ordered by `code`; combined with other equality filters Firestore may ask for a composite index and prints a creation link. Course code search is case-insensitive because codes are stored upper-cased.

### Later modules

Enrollments will link students to `course_offerings`; attendance, exams, marks and timetable will reference an offering id; `max_marks`/`passing_marks` on a course are defaults that the exam/marks modules may use.


## Phase 6: Students, Faculty & Enrollments

These collections and fields are this project's own design, not official Brainware University database specifications. No data is seeded.

### Collections

- `students/{id}`: `uid`, `student_id` (upper-cased), `email`, `display_name`, `department_id`, `program_id`, `current_semester_id`, `admission_year`, `batch`, `section`, `is_active`, timestamps. Doc id = slug of `student_id`.
- `faculty/{id}`: `uid`, `faculty_id` (upper-cased), `email`, `display_name`, `department_id`, `designation`, `is_active`, timestamps. Doc id = slug of `faculty_id`.
- `enrollments/{student-doc-id}__{offering_id}`: `student_uid`, `student_id`, `course_offering_id`, `course_id`, `academic_session_id`, `semester_id`, `program_id`, `section`, `status` (`ACTIVE|DROPPED|COMPLETED`), `enrolled_at`, `dropped_at`, timestamps.

No password or ID token is stored anywhere. Authentication stays entirely with Firebase Auth; `email` and `display_name` are copied from the existing `users/{uid}` profile, never accepted from the client.

### Relationships

```
Firebase Auth uid <-> users/{uid} <-> students/{id} | faculty/{id}
students: department <- program <- current_semester (semester must belong to the program)
faculty: department
enrollments: student + course_offering (course, session, semester, program copied from the offering)
```

Creating a student/faculty profile requires an existing Firebase Auth account that is enabled, a `users/{uid}` profile with the matching role (STUDENT or FACULTY, also consistent with the `role` claim) and `is_active: true`. The profile document and the `users/{uid}` link (`student_id`/`faculty_id`, `department_id`, `program_id`, `semester_id`) are written in one Firestore batch, so a conflict leaves neither half-written. Duplicate `uid`, `student_id` or `faculty_id` return `409`; a user profile that already carries a different `student_id`/`faculty_id` returns `400`. Updating a student/faculty profile re-syncs those fields on `users/{uid}`. `uid`, the person id and `email` are immutable.

### Endpoints (`/api/v1`)

- Students: `POST /students`, `GET /students`, `GET /students/me`, `GET /students/{student_id}`, `PATCH /students/{student_id}`.
- Faculty: `POST /faculty`, `GET /faculty`, `GET /faculty/me`, `GET /faculty/{faculty_id}`, `PATCH /faculty/{faculty_id}`.
- Enrollments: `POST /enrollments`, `GET /enrollments`, `GET /enrollments/{enrollment_id}`, `PATCH /enrollments/{enrollment_id}`.

Filters: students `department_id`, `program_id`, `semester_id`, `section`, `batch`, `is_active`; faculty `department_id`, `designation`, `is_active`; enrollments `student_id`, `student_uid`, `course_offering_id`, `course_id`, `semester_id`, `status`. All lists use the same `limit`/`cursor` pagination as earlier phases.

### Authorization and security rules

- Create/update (all three entities), list students and list faculty: ADMIN only.
- `GET /students/me` and `GET /faculty/me` use only the verified token uid. A STUDENT can read only their own student profile (another student's returns `404`); a FACULTY member only their own faculty profile. Neither can modify profiles.
- Enrollments: ADMIN sees all and creates/updates. A STUDENT sees only enrollments whose `student_uid` is their own uid (the `student_uid`/`student_id` filters cannot widen this). A FACULTY member sees only enrollments in offerings assigned to them; other enrollments return `404`. There is no public or self-service enrollment endpoint.
- Roles and uids come from the verified token and Firestore profile, never from request bodies; unknown body fields are rejected with `422`.

### Enrollment lifecycle and validation

Creating an enrollment checks: student exists (`404`) and is active; offering exists (`404`) and is PLANNED or ACTIVE; its course exists and is active; student program equals offering program; student `current_semester_id` (if set) equals the offering semester; student `section` (if set) equals the offering section (all `400`). An existing ACTIVE or COMPLETED enrollment returns `409`. Re-enrolling after a DROP reactivates the same record.

Status changes (ADMIN): `ACTIVE -> DROPPED | COMPLETED`, `DROPPED -> ACTIVE` (re-validated like a new enrollment); `COMPLETED` is final. Dropping sets `dropped_at`. Other transitions return `400`.

### Firestore indexes

Lists use equality filters, `in` on `course_offering_id` (faculty view, up to 30 assigned offerings) and the default `__name__` order. No composite indexes are predefined; verify filter combinations using the target database and trusted administrative tooling.

### Later modules

Attendance, marks and results will reference `enrollments` (student + offering). The timetable and faculty workload will use `faculty` and `course_offerings`.


## Phase 7: Attendance Management

No attendance data is seeded or generated; every record is entered by an ADMIN or the assigned FACULTY member.

### Architecture

`routers/attendance.py` -> `schemas/attendance.py` -> `services/attendance.py` -> shared Firestore helpers in `services/academic_common.py`. Authentication and roles reuse the existing Firebase ID-token dependencies (`require_roles`).

### Firestore `attendance/{attendance_id}`

`attendance_id` = `{student-doc-id}__{course_offering_id}__{YYYY-MM-DD}` (also stored as a field). Fields: `attendance_id`, `student_uid`, `student_id`, `course_offering_id`, `course_id`, `academic_session_id`, `semester_id`, `faculty_uid` (the faculty assigned when marked), `attendance_date` (ISO string), `status`, `remarks`, `marked_by_uid`, `created_at`, `updated_at`. Clients send only `student_id`, `course_offering_id`, `attendance_date`, `status` and `remarks`; everything else is derived from stored data and the verified identity, and unknown fields (including any percentage) are rejected with `422`.

### Status values and calculation

`PRESENT`, `ABSENT`, `LATE`, `EXCUSED`. Summaries are computed on the server from stored records, grouped per student and course offering:

- `total_classes` = all records; `present_count`, `absent_count`, `late_count`, `excused_count`.
- `attended_count` = `PRESENT + LATE`.
- `attendance_percentage` = `attended_count / total_classes * 100`, rounded to 2 decimals, and `0` when `total_classes` is 0.

EXCUSED counts as a held class that was not attended. That is a convention of this project, not an official Brainware University rule; change `ATTENDED` in `services/attendance.py` if policy differs.

### Validation

Before any write: the offering exists and is `ACTIVE`; its course exists and is active; the offering's semester exists and matches the offering's session and program; the caller is ADMIN or the faculty member assigned to that offering (`403` otherwise); the date is not in the future (one day slack for time zones) and falls inside the semester's date range; the student exists, is active and has an ACTIVE enrollment in that offering (`404`/`400`).

### Duplicate protection

The deterministic id means Firestore `create()` enforces one record per student + offering + date atomically (`409`). To support several sessions per day later, extend `attendance_id()` in `services/attendance.py`, the single place that defines the key.

### Bulk marking

`POST /attendance/bulk` takes one offering, one date and up to 200 entries (one per student). Every entry is validated and checked for duplicates first; then all records are written in one Firestore batch. Any failure creates nothing.

### Role permissions

- ADMIN: create, bulk create, update, view and summarize everything.
- FACULTY: create/update/view/summarize only for offerings currently assigned to them; request filters can only narrow this. Other records return `404` (or empty lists), writes return `403`.
- STUDENT: read-only; only their own records and `/attendance/me/summary`. The `student_uid`/`student_id` filters cannot widen this.
- Only `status` and `remarks` can be updated; student, offering, course, session, semester, faculty and date are immutable.

### Endpoints (`/api/v1/attendance`)

`POST /`, `POST /bulk`, `GET /` (filters: `student_id`, `student_uid`, `course_offering_id`, `course_id`, `semester_id`, `academic_session_id`, `faculty_uid`, `attendance_date`, `status`; `limit`/`cursor`), `GET /summary` (ADMIN/FACULTY; same scope filters), `GET /me/summary` (STUDENT), `GET /{attendance_id}`, `PATCH /{attendance_id}`.

### Firestore indexes

Lists use equality filters and `in` on `course_offering_id`; verify required indexes against the target database. Summaries scan the matching records (capped at 20,000) and aggregate in memory; narrow the filters for very large scopes.

### Testing

```powershell
.venv\Scripts\python -m pytest -q
```


## Phase 8: Examinations and Exam Schedules

No exam data is seeded; examination types and statuses below are configurable enums, not official Brainware University rules.

### Architecture

`routers/exams.py` -> `schemas/exams.py` -> `services/exams.py` -> shared Firestore helpers (`academic_common`). Auth reuses `require_admin` / `require_roles`; mutations write to the existing audit foundation (`examination.create|update`, `exam_schedule.create|update`; cancellation is an update with `status=CANCELLED`).

### Firestore collections

`examinations/{examination_id}` where the id is `{semester_id}__{type}__{slug(name)}` (unique per semester + type + name, `409` on duplicate). Fields: `examination_id`, `name`, `examination_type`, `academic_session_id`, `semester_id`, `program_id`, `department_id`, `start_date`, `end_date`, `status`, `description`, `created_by_uid`, `created_at`, `updated_at`.

`exam_schedules/{exam_schedule_id}` where the id is `{examination_id}__{course_offering_id}` (one schedule per offering per examination). Fields: `exam_schedule_id`, `examination_id`, `course_offering_id`, `course_id`, `academic_session_id`, `semester_id`, `program_id`, `department_id`, `exam_date`, `start_time`, `end_time`, `room`, `faculty_uid`, `max_marks`, `instructions`, `status`, `created_at`, `updated_at`.

Dates are ISO strings and times ISO `HH:MM:SS` strings, timezone-naive local academic time.

### Lifecycle and status

- Examination `type`: `MIDTERM`, `INTERNAL`, `END_SEMESTER`, `PRACTICAL`, `SUPPLEMENTARY`.
- Examination `status`: `DRAFT` (default), `SCHEDULED`, `ONGOING`, `COMPLETED`, `CANCELLED`. Status is always set explicitly by an ADMIN; nothing is calculated or mutated automatically.
- Schedule `status`: `SCHEDULED` (on create), `COMPLETED`, `CANCELLED`. Schedules cannot be created for `COMPLETED`/`CANCELLED` examinations.
- Examination `name`, type and semester are immutable; schedule examination/offering are immutable.

### Derived relationships and validation

Session, program and department of an examination come from its semester/program. A schedule's course, session, semester, program, department and faculty come from the course offering. Any of those values supplied in a request must match, otherwise `400`. The offering must belong to the examination's semester and not be cancelled. `max_marks` defaults to the course's `max_marks`. Unknown references return `404`; `start_date > end_date`, `end_time <= start_time`, non-positive `max_marks` and an `exam_date` outside the examination range return `422`. The examination range cannot be narrowed to exclude existing non-cancelled schedules (`409`).

### Conflict detection (`409`)

A new or rescheduled SCHEDULED schedule is compared with the other SCHEDULED schedules on the same date (any examination, except CANCELLED examinations) whose time overlaps. Overlap is strict, so back-to-back slots do not conflict. Checked, from stored data only: same course offering, same room (case-insensitive), same assigned faculty, and any student with an ACTIVE enrollment in both offerings. Cancelling a schedule frees its slot.

### Authorization

- ADMIN: create/update/view/list everything.
- FACULTY: read non-draft examinations of the semesters of their assigned offerings, and schedules of offerings assigned to them. Other schedules return `404`.
- STUDENT: read non-draft examinations of their own semester, and schedules of offerings they are actively enrolled in.
- Only ADMIN can create or modify examinations and schedules.

### Endpoints (`/api/v1`)

`POST|GET /examinations`, `GET /examinations/me` (STUDENT), `GET /examinations/faculty/me` (FACULTY), `GET|PATCH /examinations/{examination_id}`; `POST|GET /exam-schedules`, `GET|PATCH /exam-schedules/{exam_schedule_id}`. Examination filters: `academic_session_id`, `semester_id`, `program_id`, `department_id`, `examination_type`, `status`. Schedule filters: `examination_id`, `course_offering_id`, `course_id`, `academic_session_id`, `semester_id`, `program_id`, `department_id`, `faculty_uid`, `exam_date`, `status`. Pagination is `limit` / `cursor` as elsewhere. Schedule reads include `examination_name`, `course_code`, `course_name` and `section`.

### Indexes and limits

Admin listings use equality filters with the default order. Faculty and student schedule listings first resolve their offerings (an `in` query in chunks of 30) and sort and paginate in memory, capped at 2,000 records. No composite indexes are predefined; validate them against the target database.

### Testing

```powershell
.venv\Scripts\python -m pytest -q
```


## Phase 9: Marks, Grades, Results, SGPA and CGPA

**The grading scale is configuration, not a built-in rule.** No grade bands, grade points or pass rules are hard-coded, and none are claimed to be official Brainware University values. Before any production academic use, the project owner must supply the official scheme and an ADMIN must load it with `PUT /api/v1/grading-scheme`. The numbers used in the test-suite are test fixtures only.

### Pipeline

Enrollment -> Mark (components -> total -> percentage -> grade -> grade point) -> Semester Result (credits, SGPA) -> CGPA.

`routers/results.py` -> `schemas/{marks,results}.py` -> `services/{marks,results,grading}.py` -> shared Firestore helpers. All arithmetic uses `Decimal`, rounded half-up to 2 places; results are stored as numbers.

### Grading configuration

Stored in `settings/grading_scheme`. A scheme is a list of bands `{grade, min_percentage, max_percentage, grade_point, is_pass}`. Validation: bands must tile 0-100 with no gap or overlap, grade labels are unique and grade points are 0-10. A band covers `min <= p < max`; the band ending at 100 includes 100. `calculate_grade(percentage, scheme)` returns grade and grade point and rejects values outside 0-100, NaN and infinity. Replacing the scheme does not rewrite old marks: run `POST /api/v1/grading-scheme/regrade {semester_id}` (ADMIN) to re-apply it and regenerate that semester's results (published results whose content changes are unpublished). Marks entered before any scheme exists store no grade.

### `marks/{mark_id}`

Id: `{student}__{course_offering_id}__{examination_id}` (one mark per student, offering and examination; `409` on duplicate). Fields: `mark_id`, `student_uid`, `student_id`, `course_offering_id`, `course_id`, `examination_id`, `exam_schedule_id`, `academic_session_id`, `semester_id`, `internal_marks`, `external_marks`, `practical_marks` (each optional), `*_max_marks` (optional), `total_marks`, `max_marks`, `percentage`, `grade`, `grade_point`, `status` (`DRAFT` | `FINAL`), `remarks`, `entered_by_uid`, `verified_by_uid`, `created_at`, `updated_at`.

- At least one component is required; only the components present are summed.
- `max_marks` is the exam schedule's `max_marks` when a schedule exists for the offering and examination, otherwise the course's `max_marks`.
- Component maximums are optional; if given they must be given for every entered component, each mark must not exceed its maximum and the maximums must add up to `max_marks`. The total can never exceed `max_marks`; negative values are rejected.
- Student uid, course, session and semester are derived from verified records; totals, percentage, grade and grade point are always calculated and cannot be sent (unknown fields return `422`).
- Required relationships: active student, active/completed enrollment in the offering, examination in the same semester and session as the offering and not DRAFT or CANCELLED, and a matching exam schedule if one is supplied.
- Ownership fields (student, offering, examination, session, semester) cannot be changed by `PATCH`.

### Mark workflow and visibility

`DRAFT` marks are working entries and never count towards results. Only an ADMIN can create or set `FINAL` (which records `verified_by_uid`). FACULTY can enter and edit `DRAFT` marks for offerings assigned to them; finalized marks are admin-editable only. Students see only their own `FINAL` marks.

### `results/{student}__{semester_id}`

Fields: `result_id`, `student_uid`, `student_id`, `academic_session_id`, `semester_id`, `program_id`, `examination_type`, `courses[]` (per course: `course_id`, code, name, `course_offering_id`, `credits`, `status`, `mark_id`, marks, `percentage`, `grade`, `grade_point`, `passed`, `earned_credits`), `total_credits`, `earned_credits`, `total_marks`, `max_marks`, `percentage`, `sgpa`, `status`, `published`, `published_at`, `published_by_uid`, `generated_by_uid`, timestamps.

Generation (`POST /results/generate`, ADMIN) is deterministic and derived only from stored data:

1. Take the student's ACTIVE/COMPLETED enrollments in the semester.
2. For each course take `credits` from the course record (never from the request); a course reached through two offerings is counted once (the extra is marked `DUPLICATE`).
3. Take that offering's `FINAL` mark for examinations of the requested `examination_type` (default `END_SEMESTER`). Grade and grade point are recomputed from the current scheme.
4. A course with no FINAL mark is `MISSING` (several FINAL marks of that type: `AMBIGUOUS`). Missing marks are never treated as zero: the result is `INCOMPLETE` and `sgpa` is null.
5. `earned_credits` = credits of graded courses whose band has `is_pass: true`.
6. `total_credits` counts every counted course, graded or not; `total_marks`, `max_marks` and `percentage` aggregate the graded courses.

Results are kept in step with marks: creating or updating a mark regenerates an existing result for that student and semester synchronously. If a published result would change, it is automatically unpublished for re-review.

### Formulas

```
SGPA = sum(credit x grade_point) / sum(credit)              (null when there are no credits)
CGPA = sum(semester credits x semester SGPA) / sum(semester credits)
```

CGPA is a credit-weighted mean, not a plain average of SGPAs. It uses COMPLETE semesters only (published ones for students); other semesters are excluded and counted in `semesters_excluded`, and `status` is `COMPLETE`, `PARTIAL` or `NO_DATA`. A semester with no result record at all cannot be detected and is simply absent.

### Publication

New and regenerated results start unpublished. An ADMIN publishes (`POST /results/{id}/publish`, which recomputes first and only accepts `COMPLETE` results) or unpublishes (`POST /results/{id}/unpublish`). Students only ever see published results, SGPA and CGPA.

### Authorization

- ADMIN: everything, including unpublished results and any student's SGPA/CGPA (`/results/sgpa`, `/results/cgpa?student_id=`).
- FACULTY: create/edit non-final marks and read marks for assigned offerings only; result reads are limited to the course rows of their assigned offerings, with no aggregates (no SGPA/credit totals).
- STUDENT: read-only; own FINAL marks and own published results, SGPA and CGPA.
- Roles come from the verified token/profile, never the request body.

### Endpoints (`/api/v1`)

- Grading: `GET|PUT /grading-scheme`, `POST /grading-scheme/regrade`.
- Marks: `POST|GET /marks`, `GET /marks/me`, `GET|PATCH /marks/{mark_id}`. Filters: `student_id`, `student_uid`, `course_id`, `course_offering_id`, `examination_id`, `semester_id`, `academic_session_id`, `grade`, `status`.
- Results: `POST /results/generate`, `GET /results`, `GET /results/me`, `GET /results/me/sgpa`, `GET /results/me/cgpa`, `GET /results/sgpa` and `GET /results/cgpa` (ADMIN, `student_id` query), `GET /results/{result_id}`, `POST /results/{result_id}/publish|unpublish`. Filters: `student_id`, `semester_id`, `academic_session_id`, `program_id`, `status`, `published`. Pagination is `limit`/`cursor`.

### Limits and indexes

Result generation reads one student's enrollments and marks for a semester. Faculty result listing and CGPA read their candidate sets in memory (capped at 2,000 records). Result regeneration after a mark change is best-effort: a failure is logged and the mark write still succeeds; an ADMIN can re-run `POST /api/v1/results/generate`. Regeneration is not transactional, so concurrent edits to the same student could leave a stale result until a successful regeneration. Publication now refuses to proceed if recalculation fails. No composite indexes are predefined; validate them against the target database.

### Testing

```powershell
.venv\Scripts\python -m pytest -q
```


## Phase 10: Timetable and Notices

Both modules follow `routers -> schemas -> services -> Firestore`, reuse the shared helpers (`academic_common`, cursor pagination, `_apply`, audit) and the existing role dependencies. No DELETE endpoints exist: entries and notices are retired with `is_active` so the documents are preserved.

### Timetable (`timetable/{timetable_id}`)

A weekly recurring slot of a course offering. Ids are server-generated (`tt_<random>`). Fields: `timetable_id`, `academic_session_id`, `semester_id`, `program_id`, `department_id`, `section`, `course_offering_id`, `course_id`, `faculty_uid`, `day_of_week` (`MONDAY`..`SUNDAY`), `start_time`, `end_time` (naive `HH:MM:SS`), `room`, `class_type` (`LECTURE`, `LAB`, `TUTORIAL`, `PRACTICAL`, `OTHER`), `is_active`, `created_by_uid`, `created_at`, `updated_at`.

- Only `course_offering_id`, day, times, room and class type are required input. Session, semester, program, department, section, course and faculty are derived from the offering; if a client supplies any of them and it disagrees, the request fails with `400`. The offering must not be cancelled/completed.
- `end_time` must be after `start_time` (`422`). `PATCH` can change day, times, room, class type and `is_active`; the offering link and derived fields are immutable (`422` if sent).
- Faculty is whoever is assigned to the offering at creation time. If an offering is reassigned later, existing timetable rows keep the old `faculty_uid` until recreated.

**Conflict rules (`409`).** Against active entries of the same academic session and weekday, with strict overlap (`existing_start < new_end and new_start < existing_end`, so back-to-back slots are fine):

1. same course offering,
2. same room (case-insensitive),
3. same faculty member,
4. any student actively enrolled in both offerings.

Conflicts are re-checked when a `PATCH` changes day/time/room or re-activates an entry. Deactivated entries free their slot. Rooms are not scoped per campus/building; rooms are compared by their text.

**Access.** ADMIN: create, update, list everything. FACULTY: read active entries of offerings assigned to them. STUDENT: read active entries of offerings they are actively enrolled in. Unrelated entries return `404`. Faculty/student lists are sorted by weekday then start time.

### Notices (`notices/{notice_id}`)

Fields: `notice_id`, `title`, `description`, `audience`, `department_id`, `program_id`, `semester_id`, `academic_session_id`, `creator_uid`, `creator_role`, `priority` (`NORMAL`, `IMPORTANT`, `URGENT`; a label only, no ranking), `publish_at`, `expiry_at`, `is_published`, `is_active`, `attachment_url` (optional http(s) link; no upload/storage), `metadata` (small flat key/value map), `created_at`, `updated_at`. Creator fields are set by the server.

**Audience model.**

| audience | target required | who receives it |
|---|---|---|
| `ALL` | none | every student and faculty member |
| `STUDENTS` | none | all students |
| `FACULTY` | none | all faculty |
| `DEPARTMENT` | `department_id` | students and faculty of that department |
| `PROGRAM` | `program_id` | students of the program; faculty with an offering in it |
| `SEMESTER` | `semester_id` | students currently in the semester; faculty with an offering in it |

A student's scope comes from `students/{id}` (department, program, `current_semester_id`); a faculty member's from `faculty/{id}` and their assigned offerings. Request data is never used for it. Targets are validated and the academic chain (semester -> program -> department, session) is derived. A notice is *live* when `is_active`, `is_published`, `publish_at <= now` (or unset) and `now < expiry_at` (or unset). Non-admins only ever see live, matching notices (others return `404`). Naive timestamps are read as UTC; `expiry_at` before `publish_at` is rejected (`422` on create, `400` on update).

**Management.** ADMIN only (faculty notice creation is not enabled): create, update, `is_active` (activate/deactivate), `is_published` (publish/unpublish; create with `is_published=false` for a draft). Changing the audience re-derives the targets and requires the new target ids to be sent with it.

### Endpoints (`/api/v1`)

- Timetable: `POST|GET /timetable`, `GET /timetable/me` (student), `GET /timetable/faculty/me`, `GET|PATCH /timetable/{timetable_id}`. Filters: `academic_session_id`, `semester_id`, `program_id`, `department_id`, `section`, `course_offering_id`, `course_id`, `faculty_uid`, `day_of_week`, `room`, `is_active` (admin).
- Notices: `POST|GET /notices`, `GET /notices/me` (student), `GET /notices/faculty/me`, `GET|PATCH /notices/{notice_id}`. Filters: `audience`, `department_id`, `program_id`, `semester_id`, `academic_session_id`, `priority`, plus `is_active`/`is_published` (admin).
- Pagination is the shared `limit`/`cursor`. Audit actions: `timetable.create|update`, `notice.create|update|activate|deactivate|publish|unpublish`.

### Limits and indexes

Conflict checks and the faculty/student/notice feeds read their candidate sets in memory (capped at 2,000 records). No composite indexes are predefined; validate filter combinations against the target database. Conflict checks are read-then-write, not transactional, so two simultaneous requests could both pass.

### Testing

```powershell
.venv\Scripts\python -m pytest -q
```


## Phase 11: Reports, Analytics, Audit Logs, Sessions

All values below are computed from stored Firestore data. Nothing is simulated, random, or pre-filled.

### Reporting architecture
`routers/ops.py` (thin) -> `services/reports.py` -> existing phase services (`students`, `faculty`, `courses`, `attendance`, `exams`, `results`, `enrollments`). Reports reuse those services' role scoping instead of re-implementing security, so a caller can only narrow, never widen, what they can see. Each report returns `{summary, items, next_cursor}`; `summary` covers all rows matching the filters, `items` is paginated with the same `limit`/`cursor` convention.

| Endpoint | ADMIN | FACULTY | STUDENT |
|---|---|---|---|
| `GET /api/v1/reports/students` | yes | 403 | 403 |
| `GET /api/v1/reports/faculty` | yes | 403 | 403 |
| `GET /api/v1/reports/courses` | all | courses of assigned offerings | 403 |
| `GET /api/v1/reports/attendance` | all | assigned offerings | own only |
| `GET /api/v1/reports/examinations` | all | assigned offerings (non-draft) | own enrollments (non-draft) |
| `GET /api/v1/reports/results` | all | course rows of assigned offerings, no aggregates | own published only |
| `GET /api/v1/reports/enrollments` | all | assigned offerings | own only |

Filters: `academic_session_id`, `semester_id`, `department_id`, `program_id`, `course_id`, `course_offering_id`, `student_id`, `faculty_id` (faculty document id, resolved to a uid; ADMIN only for attendance), `from_date`/`to_date` where a date exists (attendance date, exam date, enrollment date).

### Analytics architecture
- `GET /api/v1/analytics/admin` (ADMIN): Firestore `count()` aggregations only (no documents read): active students/faculty, departments, programs, courses, offerings, ACTIVE enrollments, examinations, attendance records, published results, active notices (`is_active` and `is_published`; publish/expiry dates are not evaluated). An empty database returns zeros.
- `GET /api/v1/analytics/faculty/me` (FACULTY): assigned offerings, distinct actively-enrolled students, attendance records, upcoming SCHEDULED exam schedules (`exam_date >= today`), live notices, and `pending_marks` = active enrollments x non-cancelled exam schedules of the offering that have no mark document. `attendance_completion_percentage` is always `null`: the data model stores no planned class count, so completion cannot be determined without guessing.
- `GET /api/v1/analytics/student/me` (STUDENT): enrollments, attendance summary, upcoming exams, published results, SGPA, CGPA, timetable and notices, all via the existing services for the authenticated uid. A student without a profile gets empty values and `cgpa: null`. No uid/student id parameter is accepted.

Scan limits and optimization path: report/analytics lists are collected in memory, capped at 2,000 documents (attendance 20,000); beyond that the API answers 400 asking to narrow the filters. Services are modular so a metric can later be replaced with `count()`/`sum()` aggregations or maintained counters.

### Audit logs
Collection `audit_logs/{audit_id}` (id = Firestore document id, exposed as `audit_id`): `actor_uid`, `actor_role`, `action`, `resource_type`, `resource_id`, `timestamp` (UTC), `metadata`. Metadata keys containing `password`, `token`, `secret`, `private_key`, `credential`, `authorization`, `api_key`, `apikey` are dropped recursively before writing. Mutations are audited (create/update, publish/unpublish, activate/deactivate, bulk attendance, results generation, user create/activate/deactivate/role change); GET requests and heartbeats are not.

`GET /api/v1/audit-logs` (ADMIN only; 403 for faculty/students). Filters: `actor_uid`, `actor_role`, `action`, `resource_type`, `resource_id`, `from`, `to` (ISO datetimes; offset-free values mean UTC), `limit`, `cursor`. Document-ID order by default, timestamp order when a time range is provided.

`PATCH /api/v1/users/{uid}` (ADMIN, new in this phase): `is_active` and `role` only. Keeps the Firebase Auth disabled flag / role claim and `users/{uid}` in sync and writes `user.activate`, `user.deactivate`, `user.role_change`. Admins cannot deactivate or change the role of their own account.

### Session tracking and active users
Collection `user_sessions/{session_id}`: `session_id` (server generated `ss_<uuid>`), `uid`, `role`, `login_at`, `last_seen_at`, `logout_at`, `is_active`, `user_agent` (truncated to 300 chars), `metadata` (max 10 small, sanitized keys), `created_at`, `updated_at`. No tokens are stored. `uid` and `role` come only from the verified ID token.

- `POST /api/v1/sessions`: deliberate session start (any authenticated role). Sessions are never created automatically by other requests.
- `PATCH /api/v1/sessions/{id}/heartbeat`: owner or ADMIN; updates `last_seen_at` only. Closed session: 409. Someone else's session: 404.
- `POST /api/v1/sessions/{id}/logout`: owner or ADMIN; sets `logout_at`, `is_active=false`; the document is kept. Repeating logout is idempotent.

`GET /api/v1/analytics/active-users` (ADMIN only):
- **active** = `is_active == true` AND `last_seen_at` within `SESSION_ACTIVE_WINDOW_SECONDS` (default 300).
- **recently active** = any session (open or closed) seen within `SESSION_RECENT_WINDOW_SECONDS` (default 86400).
- Counts are distinct users, broken down by role. Registered totals (`total_users`, `total_students`, `total_faculty`, `total_admins`) come from `users` documents and are reported separately; a profile existing never makes a user "online". Firebase Auth totals are not queried.
- `include_sessions=true` adds only `session_id`, `uid`, `role` per active session.

Active-user counts are based on real tracked sessions and recent activity, not simulated counters. If clients do not call the session endpoints, the count is honestly zero. Sessions whose client never logs out simply age out of the active window.

### Privacy and security
Roles come from the verified token/profile, never from request bodies. Students see only their own analytics, sessions, attendance, enrollments and published results; faculty are scoped to assigned offerings; audit logs, active users and system-wide analytics are ADMIN only. Passwords, tokens, keys and service-account data are never returned, stored in sessions, or written to audit metadata.

### Firestore indexes
Not created by this repo; verify in the Firebase console when first queried. `count()` aggregations on single fields need no composite index. Likely composite indexes: `audit_logs` equality filters + `timestamp` range; `attendance` equality filters + `attendance_date` range (reports); `user_sessions` `is_active` == plus `last_seen_at` range. Firestore reports the exact index to create in the error link if one is missing.

### Environment and testing
New variables: `SESSION_ACTIVE_WINDOW_SECONDS`, `SESSION_RECENT_WINDOW_SECONDS` (see `.env.example`). Tests use an in-memory Firestore fake and need no credentials: `python -m pytest -q` (Phase 11: `tests/test_audit_logs.py`, `test_sessions.py`, `test_analytics.py`, `test_reports.py`).
