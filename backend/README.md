# Card Tracker Platform API

Multi-tenant FastAPI backend for the vendor platform: shop storefronts, live
stock, and reservations. This is the Phase 0 foundation. The existing Tkinter
desktop app is unchanged and still uses its own SQLite database.

## What is implemented

- Multi-tenant data model: tenants, settings, users, cards, stock,
  reservations, reservation lines, stock movements, notifications, idempotency,
  special-order requests, restock alerts.
- Public storefront: shop directory, shop profile, stock search/filters/facets,
  reservation create, reservation lookup, reservation cancel, restock-alert
  subscribe/unsubscribe, special-order request create/track/accept/cancel.
- Optional global customer accounts: email OTP sign-in, `/v1/me` reservations,
  special orders, restock alerts, a notification delivery log, and push-device
  diagnostics, plus automatic claiming of unowned guest rows that match the
  verified email. Guest tokens and guest flows remain valid and unchanged.
- Staff API: login, stock list/create/update/adjust/sell, reservation queue,
  status transitions, completion with partial quantities, dashboard, settings,
  audit trail, staff management, special-order quote/decline/convert, and
  per-variant "customers waiting" counts.
- Reservation engine: all-or-nothing holds, stock conflict handling, customer
  cancellation, expiry, completion, movement ledger, idempotency keys.
- Postgres RLS policies in the migrations; tenant context is set for public
  shop requests, staff requests, the expiry worker, and the demo seed. Compose
  runs migrations as the schema owner and the API/workers as a separate
  non-owner role.
- Restock alerts fire automatically when a variant returns to stock (manual
  adjust, PATCH, create, CSV import, offline → online toggle, or reservation
  release).
- Notification outbox delivery worker with retry/backoff, console and SMTP
  backends, per-tenant RLS iteration, and quote-expiry handling in the expiry
  worker. The same worker drains global OTP challenges; OTP codes are derived
  with HMAC and never stored or logged in plaintext. The `none` backend leaves
  queued mail untouched.
- Validation errors are redacted (no `input`/`ctx`) and guest idempotency
  tokens are derived with HMAC rather than stored. Restock alerts return a
  signed, stateless manage token; unsubscribe works with the token in the app,
  from the HTML confirmation page, or via an RFC 8058 one-click POST. Restock
  emails include a card deep link and `List-Unsubscribe` headers.
- Expiry, notification, and nightly Scryfall pricing workers; Scryfall bulk
  importer and demo seed command.
- Pytest suite running on SQLite for fast local/CI feedback, plus a
  PostgreSQL-only suite for RLS, tenant context, and last-copy locking.

## Local setup

The repository root `.venv` is ignored by git:

```bash
python3 -m virtualenv .venv
.venv/bin/pip install -e "backend[dev]"
```

Run the API from `backend/`:

```bash
cd backend
CARDTRACKER_AUTO_CREATE_TABLES=true ../.venv/bin/uvicorn app.main:app --reload
```

Interactive docs: `http://127.0.0.1:8000/docs`.

By default this uses SQLite (`backend/cardtracker_platform.db`) so the API can
be run without infrastructure. Postgres is the intended production database.

## Seed a demo shop

Create the schema first if the API has not been started yet:

```bash
cd backend
CARDTRACKER_DATABASE_URL=sqlite+pysqlite:///./cardtracker_platform.db \
  ../.venv/bin/alembic upgrade head
```

Then seed:

```bash
cd backend
../.venv/bin/python -m app.cli.seed_demo \
  --slug bolt-shop \
  --name "Bolt Shop" \
  --email owner@example.com \
  --password secret-password
```

This creates a tenant, settings, owner, three sample cards, and stock rows.
It sets tenant context before tenant-owned inserts (so it works with the
non-owner application role) and uses the owner email as both the contact and
notification address. It prints the shop slug and login details.

## Import Scryfall bulk data

Stock CSV imports match the global card catalog by set code and collector
number. Load the Scryfall catalog into the same database used by the API before
importing shop stock. This is a one-time initial setup; run the importer again
when you want to refresh catalog data.

After running the migration, download a Scryfall default-cards JSONL file and
run the importer from `backend/`, using the API's database URL:

```bash
cd backend
CARDTRACKER_DATABASE_URL=sqlite+pysqlite:///./cardtracker_platform.db \
  ../.venv/bin/python -m app.cli.import_scryfall --path ../scryfall_default_cards.jsonl
```

For Postgres, set `CARDTRACKER_DATABASE_URL` to the same application database
URL used by the API. Do not use the migration/owner URL. The importer is
idempotent and can be rerun to update existing Scryfall records.

Options:

- `--limit N` for a quick subset.
- `--batch N` commit interval (default 500).
- `--store-raw` keep the full Scryfall object in `cards.raw`; default is off to
  keep the production database small.

When automatic Scryfall pricing is enabled in **Settings → Stock pricing**,
newly imported stock uses the matching finish's Scryfall market price. Prices
below the configured minimum are set to that minimum; prices at or above it
receive the configured percentage markup and round upward to the next whole
shop-currency unit. The `scryfall-pricing` worker refreshes Scryfall default
card prices nightly at 02:00 UTC and reapplies prices to configured shops.
Rows without a Scryfall price are skipped during import, while existing stock
keeps its last price when a market price is unavailable. Currency conversion
uses the latest published daily reference rate when the shop currency has no
matching Scryfall price currency.

For an existing catalog, make sure market prices have been loaded before
expecting a Settings change to affect stock. Run the `scryfall-pricing` worker
at least once, or re-import the full default-cards JSONL file with the command
above. Saving pricing settings reports how many stock prices were updated and
how many rows were left unchanged because no finish-specific market price was
available.

## Postgres / Docker

Copy `.env.example` to `.env`, change `CARDTRACKER_JWT_SECRET`, then:

```bash
cd backend
docker compose up --build
```

The API container runs `alembic upgrade head` before starting. The `worker`
container releases expired reservations and quotes every 60 seconds; the
`notifications` container drains the email and native-push outboxes every 10
seconds; and `scryfall-pricing` refreshes catalog prices nightly.

Compose separates database roles:

- **`cardtracker_owner`** owns the schema and runs Alembic migrations via
  `CARDTRACKER_MIGRATION_DATABASE_URL`.
- **`cardtracker_app`** is the non-owner/non-superuser role used by the API and
  workers through `CARDTRACKER_DATABASE_URL`. Postgres RLS is only
  effective for this role.

The role and default table/sequence grants are created by
`scripts/init-db.sql` on first database initialization. If you reuse an older
Postgres volume, create the app role manually or reset the volume once.

Notification delivery is controlled by `CARDTRACKER_NOTIFICATION_BACKEND`:
`console` (default, logs only the rendered subject), `smtp` (requires the
`CARDTRACKER_SMTP_*` variables), or `none` (leaves the outbox pending so it can
be drained after delivery is enabled). Set `CARDTRACKER_PUBLIC_API_URL` to the
externally reachable API origin so restock unsubscribe links work in email;
`CARDTRACKER_UNSUBSCRIBE_SECRET` can hold a dedicated HMAC key (it falls back
to the JWT secret when unset). Failed sends retry with exponential
backoff (60s doubling, capped at one hour) for
`CARDTRACKER_NOTIFICATION_MAX_ATTEMPTS` attempts (default 8). The console
backend deliberately does not log recipients or message bodies, and a failed
delivery stores only the exception type and SMTP status code (never the
recipient or full error text) in the outbox row and worker log.

Native push uses the industry-standard direct providers: FCM HTTP v1 for
Android and APNs HTTP/2 token authentication for iOS. It does not use the Expo
Push Service. Set `CARDTRACKER_PUSH_BACKEND=native` and provide either
`CARDTRACKER_FCM_PROJECT_ID` plus `CARDTRACKER_FCM_CREDENTIALS_FILE`, or the
`CARDTRACKER_APNS_*` team/key/bundle settings. The `console` default logs only
the platform and never a device token or message body. Invalid provider tokens
are revoked automatically; transient provider errors share the same exponential
backoff as email. `push_tokens` stores only delivery diagnostics (`failure_count`,
`last_failure_at`, and a sanitized `last_error`), never the raw device token in
an account response. Signed-in customers can enable or disable push from the
account screen, see active/revoked devices and recent delivery status, and the
app deep-links notification taps back to the relevant shop or card.

Customer OTP behavior is configured with the `CARDTRACKER_OTP_*` variables and
`CARDTRACKER_CUSTOMER_ACCESS_TOKEN_MINUTES` (default 720, or 12 hours). Set
`CARDTRACKER_OTP_SECRET` to a dedicated random HMAC key; it falls back to the
JWT secret when unset. `CARDTRACKER_OTP_DEBUG_CODE=true` returns the code in
the request response only in `development` or `test`, and must stay off in
production. The OTP email is delivered by the notifications worker, so that
worker must be running for sign-in to work when using `smtp`. With the
`console` backend the worker logs only the subject, so use the debug code
locally or configure SMTP.

For a manual migration, use the owner/migration URL:

```bash
cd backend
CARDTRACKER_MIGRATION_DATABASE_URL=postgresql+psycopg://... \
  ../.venv/bin/alembic upgrade head
```

## RLS notes

Tenant-owned tables have row-level security. The application must call:

```sql
SELECT set_config('app.tenant_id', '<tenant uuid>', true);
```

in the same transaction before reading tenant-owned rows. The FastAPI
dependencies and services do this for staff, public shop, and worker requests;
the demo seed calls it after creating the tenant. If you connect with a
superuser or the table owner, Postgres ignores RLS; production and Compose use
a dedicated non-owner application role. The migrations use
`FORCE ROW LEVEL SECURITY`, so an owner role is also constrained once the
policy exists, but migrations still run as the owner because DDL needs it.

Customer account requests additionally set:

```sql
SELECT set_config('app.customer_id', '<customer uuid>', true);
```

A customer token is global (no tenant claim). Permissive `*_customer_own`
policies let `/v1/me` read reservations, special orders, restock alerts, and
notification delivery rows across shops without weakening the existing
tenant-isolation policies. Reservation lines stay tenant-only: account detail
resolves the owned reservation first, then sets the tenant context before
loading lines. `notifications` keeps its tenant policy and gains a read-only
customer policy, so the worker still drains a whole shop's outbox while a
customer sees only rows with its `user_id`. Global customer rows in `users` are
allowed by a separate permissive policy. Claiming iterates shops and sets the
tenant context for each update.

`tenant_settings` is intentionally not RLS-protected because the public shop
directory reads branding across tenants. It contains no customer data.
`customer_otp_challenges` is global like `cards` and contains no plaintext OTP.

## Verify against PostgreSQL

SQLite cannot exercise row-level security, `FOR UPDATE`, or the last-copy
race, so those behaviours are covered by `tests/test_postgres.py`. The tests
skip unless both URLs are set:

```bash
export CARDTRACKER_TEST_POSTGRES_ADMIN_URL='postgresql+psycopg://postgres@127.0.0.1:55432/cardtracker'
export CARDTRACKER_TEST_POSTGRES_URL='postgresql+psycopg://cardtracker_app:cardtracker_app@127.0.0.1:55432/cardtracker'
```

`CARDTRACKER_TEST_POSTGRES_URL` must use a **non-owner, non-superuser** role,
otherwise Postgres ignores RLS. The suite creates that role and grants it
access when the admin URL is privileged enough to do so.

Three ways to get a server:

- **Portable, no Docker or root** — downloads a pinned PostgreSQL build into a
  cache directory and runs it on a spare port:

  ```bash
  ./scripts/local_postgres.sh start
  eval "$(./scripts/local_postgres.sh env)"
  ```

- **Docker** — `docker run --rm -p 55432:5432 -e POSTGRES_PASSWORD=postgres postgres:16`,
  then use the URLs above.

- **Managed** (Neon, Supabase, RDS) — use the provider's admin URL for
  migrations and a dedicated non-owner role for `CARDTRACKER_TEST_POSTGRES_URL`.

What the suite proves:

| Test | Proves |
| --- | --- |
| `test_rls_hides_other_tenants` | Tenant A never sees tenant B's stock |
| `test_requests_and_alerts_are_tenant_isolated` | Special orders and restock alerts are isolated too |
| `test_no_tenant_context_sees_no_tenant_rows` | A missing tenant context fails closed |
| `test_rls_blocks_cross_tenant_write` | `WITH CHECK` stops cross-tenant inserts |
| `test_tenant_settings_are_readable_without_tenant_context` | The directory exception stays intentional |
| `test_tenant_context_survives_commit` | The `after_begin` hook re-applies context after a commit |
| `test_customer_context_sees_only_own_rows_across_tenants` | A global customer sees its linked rows but not another customer's |
| `test_notifications_are_customer_scoped` | Customer notification rows are isolated across customers/tenants; tenant context still drains the shop outbox |
| `test_claim_updates_only_unowned_matching_email` | Email claiming is case-insensitive, idempotent, and never reassigns an owner |
| `test_app_role_can_create_a_global_customer_without_tenant_context` | Customer creation works with the global `users` policy |
| `test_last_copy_race_has_exactly_one_winner` | Two simultaneous holds on the last copy: exactly one wins |

The race test is a real regression test: removing `.with_for_update()` from
`_lock_stocks` makes both attempts succeed.

## Tests and checks

The backend package must be installed editable so `app` is importable:

```bash
.venv/bin/pip install -e "backend[dev]"
```

Then run the SQLite gate:

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests
../.venv/bin/python -m pytest --cov=app --cov-branch --cov-report=term-missing
```

The current local result is **265 passed, 13 PostgreSQL tests skipped, 100%
line and branch coverage**. The coverage floor is 100% in `pyproject.toml`, so
any new uncovered line or branch fails the command.

With the Postgres URLs exported, the same run includes the isolation,
customer-account, notification, and locking tests and reports **278 passed,
100% coverage** (277 before the added per-device logout test).
The repository helper starts the portable server and applies the URLs for you:

```bash
./scripts/test_backend_postgres.sh
```

CI runs both SQLite and PostgreSQL coverage, plus
`alembic downgrade base && alembic upgrade head` and an assertion that RLS is
enabled on every tenant table. The migration runner widens
`alembic_version.version_num` to 64 characters on Postgres so the existing
38-character `0006_customer_notification_preferences` revision id can be
written. The root `tox.ini` runs the legacy Python matrix; `make test-matrix`
skips interpreters that are not installed.

## Error responses

Reservation and special-order conflicts use `{"code", "message", "details"}`.
FastAPI validation failures return HTTP 422 with only `type`, `loc`, and
`msg` in each error; the submitted value (`input`) and context (`ctx`) are
stripped so passwords and other secrets are not echoed back. New guest
reservation idempotency responses store only the reservation id and derive the
guest token from the idempotency key with HMAC; rows written before that change
remain readable until they expire.

## API surface (Phase 0)

Public:

- `GET /v1/shops`
- `GET /v1/shops/{slug}`
- `GET /v1/shops/{slug}/stock`
- `GET /v1/shops/{slug}/stock/{stock_id}`
- `GET /v1/shops/{slug}/facets`
- `POST /v1/shops/{slug}/reservations`
- `GET /v1/reservations/{id}` with `X-Shop-Slug` and `X-Reservation-Token`
- `POST /v1/reservations/{id}/cancel` with the same headers
- `GET /v1/shops/{slug}/reservations/{public_ref}` with the token
- `POST /v1/shops/{slug}/restock-alerts` (`manage_token` is returned for the app)
- `POST /v1/shops/{slug}/restock-alerts/{id}/unsubscribe?token=...` (or JSON `{"email": "..."}`)
- `GET /v1/shops/{slug}/restock-alerts/{id}/unsubscribe?token=...` (HTML confirmation)
- `POST /v1/shops/{slug}/restock-alerts/{id}/unsubscribe/one-click?token=...` (RFC 8058)
- `POST /v1/shops/{slug}/card-requests`
- `GET /v1/card-requests/{id}` with `X-Shop-Slug` and `X-Card-Request-Token`
- `POST /v1/card-requests/{id}/accept` with the same headers
- `POST /v1/card-requests/{id}/cancel` with the same headers

Customer account (Bearer customer token unless noted; OTP request/verify and
refresh are public):

- `POST /v1/auth/otp/request`
- `POST /v1/auth/otp/verify`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout` — optional `{"refresh_token": "..."}` body; with a token
  only that device's session is revoked, while an empty body keeps the legacy
  account-wide revocation
- `POST /v1/me/sessions/revoke-all`
- `GET|PATCH /v1/me`
- `DELETE /v1/me` — soft-close the account, revoke every session, and stop
  notification delivery while keeping shop history
- `POST /v1/me/email`
- `POST /v1/me/email/verify`
- `GET /v1/me/reservations`
- `GET /v1/me/reservations/{id}`
- `POST /v1/me/reservations/{id}/cancel`
- `GET /v1/me/card-requests`
- `GET /v1/me/card-requests/{id}`
- `POST /v1/me/card-requests/{id}/accept`
- `POST /v1/me/card-requests/{id}/cancel`
- `GET /v1/me/restock-alerts`
- `DELETE /v1/me/restock-alerts/{id}`
- `GET|POST /v1/me/push-tokens`
- `DELETE /v1/me/push-tokens/{token}`
- `GET /v1/me/notifications?limit=50&cursor=...`

Staff:

- `POST /v1/staff/auth/login`
- `GET /v1/staff/me`
- `GET /v1/staff/dashboard`
- `GET /v1/staff/cards`
- `GET|POST /v1/staff/stock`
- `PATCH /v1/staff/stock/{id}`
- `POST /v1/staff/stock/{id}/adjust`
- `POST /v1/staff/stock/{id}/sell`
- `GET /v1/staff/reservations`
- `GET /v1/staff/reservations/{id}`
- `POST /v1/staff/reservations/{id}/status`
- `POST /v1/staff/reservations/{id}/complete`
- `GET|PATCH /v1/staff/settings`
- `GET /v1/staff/card-requests?status=...`
- `POST /v1/staff/card-requests/{id}/quote`
- `POST /v1/staff/card-requests/{id}/decline`
- `POST /v1/staff/card-requests/{id}/convert`

## Customer mobile app

The Expo customer app lives in [`../mobile`](../mobile). It is guest-first
with an optional account: shop directory, storefront search and pagination,
local cart, guest or signed-in reservation create/lookup/cancel, hold history,
restock alerts, special-order request/quote/cancel flows, and email OTP
sign-in. Account data is fetched from `/v1/me` and combined with device-local
guest rows. Access and refresh tokens are persisted with SecureStore on native
platforms and AsyncStorage for the web preview. Sign-out sends the current
refresh token to revoke only this device; sign-out-all revokes every session;
both clear account queries. Deleting the account is a soft close that keeps shop
history. See [`mobile/README.md`](../mobile/README.md) for setup and current
scope.

## Phase 0 gaps / before pilot

- Customer accounts are optional and use email OTP only. Refresh-token rotation,
  per-device logout, revoke-all sessions, profile editing, email change with OTP
  re-validation, and account deletion are implemented. Logout without a refresh
  token still revokes every session for older clients; the mobile app sends its
  current token. Account emails are global per verified email across shops.
- Deleting an account is a soft close: it deactivates the customer, revokes every
  refresh session, stops notification delivery, and keeps reservations, special
  orders, and restock alerts with their shops. An already-issued access token is
  rejected on the next request because `is_active` is checked.
- Special-order quotes are indicative. Conversion creates the linked reservation
  at the stock row's current shelf price, not at the quoted price.
- Native FCM/APNs delivery is implemented, but a real end-to-end send needs a
  Firebase service-account JSON, an APNs `.p8` key, provider project setup, and
  a physical device. Staff in-app notifications still exist only in the outbox;
  they are not surfaced in the admin yet.
- Restock alerts and special orders created while signed out stay device-local
  until a customer verifies the same email and claims them. The persisted query
  cache can include account data while signed in; sign-out removes account
  queries from it.
- The mobile app has native push registration/deep links, QR/deep-link entry,
  card detail, restock alerts, special orders, optional OTP accounts, offline
  query caching, localization, and a browser smoke suite. A real-device signed-in
  E2E suite is still outstanding.
- PostgreSQL-only tests skip unless `CARDTRACKER_TEST_POSTGRES_ADMIN_URL` and
  `CARDTRACKER_TEST_POSTGRES_URL` are set; SQLite cannot prove RLS or locking.
- Rate limiting is in-process, so it assumes a single API worker.
- The root `make check` excludes `backend/`; use the backend commands above.
