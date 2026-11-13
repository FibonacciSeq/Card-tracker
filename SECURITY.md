# Security policy

## Supported versions

Card Tracker is currently a pre-1.0 project with a legacy Tkinter desktop app
and a multi-vendor platform (`backend/`, `admin/`, `mobile/`). Security fixes
are applied to the latest release and to `main`.

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |
| older | No |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's
private vulnerability reporting:

<https://github.com/aleksacvele/card-tracker/security/advisories/new>

Include:

- the affected version or commit,
- steps to reproduce,
- the impact you believe it has, and
- any suggested fix or mitigation.

You can expect an acknowledgement within a few business days. Please allow time
for a fix before publishing details.

## Local customer data

The customer and owner apps share `cardtracker_shop.db` (or the file named by
`CARDTRACKER_SHOP_DB`). It contains names, e-mail addresses, phone numbers,
order notes, and order history. It is intentionally excluded from Git.

- Keep the database on a trusted, access-controlled machine or share.
- Restrict filesystem permissions to the account that runs the shop.
- Do not attach the database, exports, or screenshots containing customer data
  to public issues or pull requests.
- Back it up securely. The SQLite file is not encrypted at rest; use full-disk
  or volume encryption if the machine is shared or portable.
- Delete customer data when it is no longer needed, and follow applicable local
  privacy rules.

The SQL Server schema in `database/` stores the same kind of data in a
multi-user deployment. Apply the same access control, backup, and retention
rules there.

The platform backend stores shop, customer, reservation, restock-alert, and
special-order data in PostgreSQL in production (SQLite locally). Treat database
dumps, API logs, and notification payloads as sensitive. The mobile app keeps a
local cart, guest token material, and the guest metadata needed to reopen a
hold, manage a restock alert, or track a special order. When a customer signs
in, `/v1/me` data lives in the React Query cache and may be included in the
persisted offline query cache; sign-out removes account queries from that cache.

## Mobile app tokens

- Customer account access tokens are 12-hour JWTs. The backend also issues an
  opaque 7-day refresh token that rotates on use and supports per-device logout
  and revoke-all session actions. The mobile app persists both tokens with
  SecureStore on native platforms and AsyncStorage on web, restores the session
  on cold launch, and clears local session state on a failed refresh or sign-out.
  Normal sign-out sends the current refresh token so only that device is
  revoked; a body-less `/v1/auth/logout` keeps the legacy account-wide behavior
  for older clients.
- Guest reservation, restock-alert manage, and special-order tokens are
  credentials. Native builds store them in Expo SecureStore; the web preview
  falls back to AsyncStorage because SecureStore has no web implementation. Do
  not use the web preview as a production customer channel.
- Restock unsubscribe links use a stateless HMAC token scoped to one tenant and
  one alert. The token is deterministic, returned as `manage_token`, and grants
  only the ability to unsubscribe that alert. The confirmation page sends
  `Referrer-Policy: no-referrer` and `Cache-Control: no-store`; the token may
  still appear in API access logs, so keep log retention short.
- Restock emails include `List-Unsubscribe` and `List-Unsubscribe-Post`
  headers for RFC 8058 one-click unsubscribe, plus a human-facing confirmation
  link. The one-click endpoint is idempotent and returns HTML.
- Set `CARDTRACKER_PUBLIC_API_URL` to the public HTTPS API origin so email
  links do not point at localhost. Set `CARDTRACKER_UNSUBSCRIBE_SECRET` to a
  dedicated random key in production; when unset, the JWT secret is used.
- Email OTP codes are six digits, expire after 10 minutes, allow five attempts,
  and are rate-limited per client IP and per hashed email. The code is derived
  with HMAC from the challenge id and `CARDTRACKER_OTP_SECRET` (or the JWT
  secret when unset); no plaintext code is stored in the database or written
  to logs. The notification worker renders it only at delivery time.
- `CARDTRACKER_OTP_DEBUG_CODE` returns the code in the request response only in
  `development` or `test`. Keep it `false` in production. `/v1/auth` and
  `/v1/me` responses are sent with `Cache-Control: no-store`.
- Anyone who controls an email can claim unowned guest reservations, restock
  alerts, and special orders that use that email. This is the intended
  cross-device recovery rule and the reason the OTP is required. Rows already
  linked to another customer are never reassigned.
- Disabling or deleting a customer account blocks new OTP verification and
  takes effect on the next account request because `is_active` is checked while
  resolving the token. The backend revokes refresh-token rows on logout (the
  current device when its token is supplied), revoke-all, email change, and
  deletion. Sign-out and revoke-all cannot invalidate an already-copied access
  JWT before its 12-hour expiry; deletion and deactivation do, because the
  account status is checked on every request. Refresh rotation controls
  continuation in the normal case.
- Account deletion is a soft close, not a full erasure: the customer row is
  deactivated, every refresh session is revoked, notification delivery stops,
  and shop history plus profile/audit rows are retained. Device-local guest data
  is not removed. A full data-deletion request still needs a support-assisted
  process.
- Global customer account/session audit rows are written to
  `customer_audit_events` and scoped by PostgreSQL RLS. They store action
  metadata, never OTPs or token secrets.
- The customer notification delivery log reads tenant `notifications` rows
  through a permissive customer RLS policy limited to the active
  `app.customer_id`. `/v1/me/notifications` returns rendered titles only, not
  message bodies, so restock unsubscribe tokens are not exposed. Stored
  delivery errors are sanitized and contain no recipient, body, or device token.
- Push-token registrations are customer-scoped by RLS. The account API never
  returns the raw FCM/APNs token; it exposes only platform, timestamps, revoked
  state, failure count, last failure time, and a sanitized error. A token the
  provider rejects is revoked immediately, and transient failures keep the
  existing exponential-backoff retry behavior.
- The app sends an idempotency key when creating a reservation and reuses it
  while a submission is retried, preventing duplicate holds after a lost
  response.
- `EXPO_PUBLIC_*` environment variables are embedded in the client bundle and
  are not secret. Never put API secrets, SMTP credentials, or staff tokens in
  a mobile environment file.
- The customer app does not collect or transmit payment details; payment stays
  with the shop.

## Secrets and environment variables

SQL Server credentials are read only from environment variables:

| Variable | Purpose |
| --- | --- |
| `CARDTRACKER_MSSQL_HOST` | Server host name |
| `CARDTRACKER_MSSQL_PORT` | Server port |
| `CARDTRACKER_MSSQL_DATABASE` | Database name |
| `CARDTRACKER_MSSQL_USER` | SQL login |
| `CARDTRACKER_MSSQL_PASSWORD` | SQL password |
| `CARDTRACKER_MSSQL_TRUSTED` | Use Windows authentication |
| `CARDTRACKER_MSSQL_ENCRYPT` | Encrypt the connection |
| `CARDTRACKER_MSSQL_TRUST_CERT` | Trust a server certificate |
| `CARDTRACKER_MSSQL_ODBC_DRIVER` | ODBC driver name |
| `CARDTRACKER_MSSQL_DRIVER` | Force `pyodbc` or `pymssql` |

Do not commit credentials, `.env` files, or connection strings. `.env` and
`.env.*` are git-ignored; `.env.example` contains placeholders only.

`CARDTRACKER_MSSQL_TRUST_CERT` defaults to `1` for local development with a
self-signed SQL Server certificate. In production, use a trusted certificate
and set it to `0`. `CARDTRACKER_MSSQL_ENCRYPT` defaults to `1`.

## Application hardening already in place

- Card downloads require HTTPS; image downloads allow only HTTP(S). Image
  cache names are sanitized before use and image downloads are capped at 8 MiB.
- Remote requests use timeouts. Images and the extracted Scryfall catalog are
  written to a temporary file and atomically renamed, so an interrupted
  download cannot leave a partial file in place.
- SQL values are parameterized. The few statically assembled SQL fragments are
  built from fixed tuples; Bandit's `B608` heuristic is explicitly skipped
  after review, with the rationale recorded in `pyproject.toml`.
- Shop input is trimmed and bounded; e-mail addresses receive basic format
  validation.
- The local shop schema records a `user_version`; a database created by a
  newer application version is rejected instead of being modified blindly.
- Tk callbacks from worker threads go through `ui.dispatch.TkDispatcher`, so
  background work never touches widgets directly.

These measures reduce risk but do not make untrusted data safe. Treat the local
database and any spreadsheet imports as sensitive input.

## Dependency and code checks

Every pull request runs the checks for the parts it touches. The legacy
desktop workflow runs:

```bash
ruff check .
ruff format --check .
mypy .
pytest --cov --cov-report=term-missing
bandit -q -c pyproject.toml -r .
./scripts/audit_requirements.sh
```

The platform workflows run backend Ruff/mypy/pytest with coverage (SQLite and
PostgreSQL), admin and mobile `npm audit`, admin
ESLint/typecheck/coverage/build/Playwright, and mobile
ESLint/typecheck/coverage/web export. See [`STATUS.md`](STATUS.md) and the
component READMEs for the exact commands.

Dependabot checks Python dependencies and GitHub Actions monthly. If you add a
dependency, pin a lower bound that contains the current security fixes and
update `pyproject.toml` (the single dev-dependency source). `requirements.txt`
remains the runtime-only install list for the legacy desktop app.
