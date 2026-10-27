# Card Tracker Platform API

Multi-tenant FastAPI backend for the vendor platform: shop storefronts, live
stock, and reservations. This is the Phase 0 foundation. The existing Tkinter
desktop app is unchanged and still uses its own SQLite database.

## What is implemented

- Multi-tenant data model: tenants, settings, users, cards, stock,
  reservations, reservation lines, stock movements, notifications, idempotency.
- Public storefront: shop directory, shop profile, stock search/filters/facets,
  reservation create, reservation lookup, reservation cancel.
- Staff API: login, stock list/create/update/adjust/sell, reservation queue,
  status transitions, completion with partial quantities, dashboard, settings.
- Reservation engine: all-or-nothing holds, stock conflict handling, customer
  cancellation, expiry, completion, movement ledger, idempotency keys.
- Postgres RLS policies in the initial migration; tenant context is set for
  public shop requests, staff requests, and the expiry worker.
- Expiry worker, Scryfall bulk importer, demo seed command.
- Pytest suite running on SQLite for fast local/CI feedback.

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
It prints the shop slug and login details.

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

The API container runs `alembic upgrade head` before starting. The worker
container releases expired reservations every 60 seconds.

For a manual migration:

```bash
cd backend
CARDTRACKER_DATABASE_URL=postgresql+psycopg://... ../.venv/bin/alembic upgrade head
```

## RLS notes

Tenant-owned tables have row-level security. The application must call:

```sql
SELECT set_config('app.tenant_id', '<tenant uuid>', true);
```

in the same transaction before reading tenant-owned rows. The FastAPI
dependencies and services do this for staff and public shop requests. If you
connect with a superuser or the table owner, Postgres ignores RLS; production
should use a dedicated non-owner application role. The migration currently
uses `FORCE ROW LEVEL SECURITY`, so an owner role is also constrained once the
policy exists.

`tenant_settings` is intentionally not RLS-protected because the public shop
directory reads branding across tenants. It contains no customer data.

## Tests and checks

```bash
cd backend
../.venv/bin/python -m pytest
../.venv/bin/ruff check .
../.venv/bin/mypy app
```

Backend tests use an in-memory SQLite database. RLS, `FOR UPDATE`, and real
concurrency must also be verified against Postgres before production.

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

## Phase 0 gaps / before pilot

- Customer OTP auth and customer accounts are not implemented yet; guest
  reservations use a per-reservation access token.
- Restock alerts and special-order requests are in the spec but not yet
  implemented.
- Notification outbox rows are written, but email/push delivery workers are not.
- Excel/CSV stock import and export endpoints are not implemented.
- Postgres RLS, migrations, and last-copy concurrency need testing against a
  real Postgres instance.
- No mobile app or web admin yet. Those are Phase 1/2.
- The root `make check` excludes `backend/`; use the backend commands above.
