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
  worker. The `none` backend leaves queued mail untouched.
- Validation errors are redacted (no `input`/`ctx`), guest idempotency tokens
  are derived with HMAC rather than stored, and restock unsubscribe uses a
  JSON body instead of a query-string email.
- Expiry worker, Scryfall bulk importer, demo seed command.
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

Download a Scryfall default-cards JSONL file after running the migration,
then:

```bash
cd backend
../.venv/bin/python -m app.cli.import_scryfall --path scryfall_default_cards.jsonl
```

Options:

- `--limit N` for a quick subset.
- `--batch N` commit interval (default 500).
- `--store-raw` keep the full Scryfall object in `cards.raw`; default is off to
  keep the production database small.

## Postgres / Docker

Copy `.env.example` to `.env`, change `CARDTRACKER_JWT_SECRET`, then:

```bash
cd backend
docker compose up --build
```

The API container runs `alembic upgrade head` before starting. The `worker`
container releases expired reservations and quotes every 60 seconds; the
`notifications` container drains the email outbox every 10 seconds.

Compose separates database roles:

- **`cardtracker_owner`** owns the schema and runs Alembic migrations via
  `CARDTRACKER_MIGRATION_DATABASE_URL`.
- **`cardtracker_app`** is the non-owner/non-superuser role used by the API and
  both workers through `CARDTRACKER_DATABASE_URL`. Postgres RLS is only
  effective for this role.

The role and default table/sequence grants are created by
`scripts/init-db.sql` on first database initialization. If you reuse an older
Postgres volume, create the app role manually or reset the volume once.

Notification delivery is controlled by `CARDTRACKER_NOTIFICATION_BACKEND`:
`console` (default, logs only the rendered subject), `smtp` (requires the
`CARDTRACKER_SMTP_*` variables), or `none` (leaves the outbox pending so it can
be drained after delivery is enabled). Failed sends retry with exponential
backoff (60s doubling, capped at one hour) for
`CARDTRACKER_NOTIFICATION_MAX_ATTEMPTS` attempts (default 8). The console
backend deliberately does not log recipients or message bodies, and a failed
delivery stores only the exception type and SMTP status code (never the
recipient or full error text) in the outbox row and worker log.

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

`tenant_settings` is intentionally not RLS-protected because the public shop
directory reads branding across tenants. It contains no customer data.

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
| `test_last_copy_race_has_exactly_one_winner` | Two simultaneous holds on the last copy: exactly one wins |

The race test is a real regression test: removing `.with_for_update()` from
`_lock_stocks` makes both attempts succeed.

## Tests and checks

```bash
cd backend
../.venv/bin/python -m pytest        # SQLite: 99 passed, 7 Postgres tests skipped
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests
```

With the Postgres URLs exported, the same `pytest` run includes the isolation
and locking tests (106 passed). CI runs both, plus `alembic downgrade base &&
alembic upgrade head` and an assertion that RLS is enabled on every tenant
table.

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
- `POST /v1/shops/{slug}/restock-alerts`
- `POST /v1/shops/{slug}/restock-alerts/{id}/unsubscribe` with JSON `{"email": "..."}`
- `POST /v1/shops/{slug}/card-requests`
- `GET /v1/card-requests/{id}` with `X-Shop-Slug` and `X-Card-Request-Token`
- `POST /v1/card-requests/{id}/accept` with the same headers
- `POST /v1/card-requests/{id}/cancel` with the same headers

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

The Expo customer app lives in [`../mobile`](../mobile). It is a guest-first
vertical slice over the public API: shop directory, storefront search and
pagination, local cart, reservation create/lookup/cancel, and local hold
history. Guest tokens are stored in SecureStore on native platforms and in
AsyncStorage for the web preview. See [`mobile/README.md`](../mobile/README.md)
for setup and current scope.

## Phase 0 gaps / before pilot

- Customer OTP auth and customer accounts are not implemented yet; guest
  reservations use a per-reservation access token.
- Push notifications (FCM/APNs) are not implemented; email is the only
  delivery channel. Staff in-app notifications exist in the outbox but are not
  surfaced in the admin yet.
- Restock alerts require an email address instead of a customer account; OTP
  accounts in the mobile app will later attach them to a customer.
- The mobile app is a guest-only slice: it has no OTP accounts, push handling,
  restock-alert UI, special-order UI, QR scanner, offline cache, or device E2E
  suite yet. The API and vendor web admin are otherwise implemented.
- PostgreSQL-only tests skip unless `CARDTRACKER_TEST_POSTGRES_ADMIN_URL` and
  `CARDTRACKER_TEST_POSTGRES_URL` are set; SQLite cannot prove RLS or locking.
- Rate limiting is in-process, so it assumes a single API worker.
- The root `make check` excludes `backend/`; use the backend commands above.
