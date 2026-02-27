# Ionic Angular Frontend (New App)

This folder contains a full Ionic Angular UI for every backend capability currently implemented.

## Covered Backend Functionalities

- `GET /health`
- `GET /v1/auth/me`
- `POST /v1/auth/bootstrap-admin`
- `POST /v1/auth/users`
- `POST /v1/auth/keys`
- `POST /v1/auth/keys/revoke`
- `POST /v1/documents/ingest`
- `POST /v1/outcomes`
- `POST /v1/strategy/suggest`
- `POST /v1/corpus/scan`
- `POST /v1/corpus/learn`
- `POST /v1/corpus/update`
- `GET /v1/corpus/status`
- `GET /v1/audit/logs`

## Auth and Onboarding Flow

- `Company Registration` (`/register`):
  - Configure API base URL + tenant ID + bootstrap token
  - Bootstrap first tenant admin
- `Tenant User Login` (`/login`):
  - Sign in using API base URL + tenant ID + API key
  - Validates with `GET /v1/auth/me`
- Route guards:
  - Logged-out users are redirected to `/login`
  - Logged-in users are redirected away from auth pages
- Role-aware navigation:
  - `admin` can access user/auth management pages
  - Other roles see pages based on minimum role thresholds

## Pages

- `Overview`: feature map and current session context.
- `Setup and Health`: API base URL, tenant ID, API key, bootstrap token, health test.
- `Auth and RBAC`: bootstrap admin, current identity, create user, create key, revoke key.
- `Contracts AI`: ingest document, record outcomes, and generate strategy suggestions with `single_client` or `all_clients` scope inside the tenant.
- `Corpus Learning`: select `client_id` + source folder, scan corpus, learn/update corpus, inspect corpus status, and optionally generate synthetic outcomes from redlines/comments.
  - Includes comment analysis tuning with `strict/balanced/lenient` profile and custom accept/reject/revise phrase lists.
- `Audit Logs`: filter and inspect tenant audit trails.

## Run

```bash
cd D:/nego/ui-ionic-angular
npm install
npm start
```

App default URL:

- `http://localhost:4200`

Before using actions, configure these on `Setup and Health` page:

- API Base URL (for example `http://127.0.0.1:8000`)
- Tenant ID
- API Key (for non-bootstrap endpoints)
- Bootstrap Token (only for `bootstrap-admin`)
