# Card Tracker platform — status

Last updated: **2026-10-27**
Latest feature commit: **`e0c4d10` — Add restock alerts, special orders, and notification delivery**

This file is the quick, human-readable status of the multi-vendor platform.
The full product/technical specification lives outside the repository in the
project plan; this document records what is actually implemented, how it is
verified, and what comes next.

---

## 1. What this repository contains

The repository currently holds two things side by side:

| Part | Location | Status |
| --- | --- | --- |
| Legacy Tkinter desktop shop (customer + owner + collection tool) | root `*.py`, `ui/`, `services/`, `database/` | Working; kept unchanged as a fallback |
| Multi-vendor platform API | `backend/` | Implemented through Step 4 |
| Vendor web admin | `admin/` | Implemented through Step 4 |
| Customer mobile app | `mobile/` | **Not started** (next step) |

The platform is the forward path: one cloud API and one admin codebase serving
many shops, with a native customer app on top. The legacy desktop app remains
for the original single-shop workflow until the new stack replaces it.

### Architecture at a glance

- **API:** FastAPI + SQLAlchemy 2 + Pydantic v2 + Alembic, PostgreSQL in
  production (SQLite for fast local tests).
- **Tenancy:** every tenant-owned row carries `tenant_id`; PostgreSQL RLS is
  enabled and forced. The app role is non-owner/non-superuser. Tenant context
  is a transaction-local `app.tenant_id` setting, re-applied after commits.
- **Money:** integer minor units plus ISO currency code. No floats.
- **Admin:** Vite + React 19 + TypeScript + TanStack Query, no SSR and no
  second backend. Types are generated from a committed OpenAPI snapshot.
- **Workers:** expiry worker (holds and quotes) and notification outbox worker.
- **Notifications:** transactional outbox with console or SMTP delivery,
  retry/backoff, and per-tenant iteration so RLS stays enforced.

---

## 2. What has been done

### Phase 0 — backend foundation

- Tenant/settings/user/card/stock/reservation models and Alembic baseline.
- Public shop directory and profile, stock search with filters, facets and
  cursor pagination, card detail, and shop branding.
- Reservation engine:
  - `REQUESTED → CONFIRMED → READY → COMPLETED`, plus `CANCELLED` / `EXPIRED`.
  - All-or-nothing holds, `reserved <= quantity` protection, stock movement
    ledger, idempotency keys, partial completion, automatic expiry.
  - Guest reservations with a per-reservation access token.
- Staff auth (email + password + JWT), dashboard, settings, and role checks.
- Scryfall bulk JSONL importer and a demo seed CLI.
- Docker Compose with PostgreSQL, API, and worker services; `.env.example`;
  backend README.

### Step 2 — stock import/export

- CSV export doubles as the import template.
- Import defaults to `dry_run=true`, matches on set + collector number +
  variant (finish/condition/language), treats quantity as absolute on-hand,
  refuses to break existing holds, and records `IMPORT` movements.
- Check-then-apply UI in the admin with per-row validation feedback.

### Step 3 — staff, audit, and rate limits

- Owner staff management: add, promote/demote, deactivate, reset password;
  last-active-owner and self-deactivation guards.
- Append-only audit trail for stock, imports, reservations, settings, team,
  and special-order actions, exposed with action filters in the admin.
- In-process sliding-window rate limits on staff login, reservation creation,
  restock subscriptions, and special-order creation.
- Migration `0002_audit_and_user_status`.

### Step 4 — restock alerts, special orders, notifications

Restock alerts:

- Guest email subscriptions per card + finish/condition/language.
- Idempotent subscribe; unsubscribe with alert id + email (always returns 204).
- One-shot `notified_at`; alerts fire when a variant returns to stock via
  create, update, manual adjust, or CSV import.
- No notification while stock is offline or still unavailable.
- Admin stock rows show a “N waiting” demand badge.

Special orders:

- Guest create/track/accept quote/cancel with a per-request access token.
- Statuses: `REQUESTED → QUOTED → ACCEPTED → CONVERTED`, plus `DECLINED`,
  `EXPIRED`, `CANCELLED`.
- Staff queue with quote (price, optional expiry, note), decline, and convert.
- Conversion requires the exact catalog card and variant in stock, creates a
  linked `CONFIRMED` reservation, and holds stock immediately.
- Stale quotes expire automatically in the expiry worker.

Notifications:

- Outbox delivery worker iterating tenants to satisfy RLS.
- `console` (default) and `smtp` backends using the standard library; `none`
  disables delivery.
- Retry with 60 s doubling backoff, capped at one hour, default 8 attempts.
- Customer and staff emails for reservation lifecycle, quote/decline/accept,
  conversion, and restock events.
- Docker Compose `notifications` worker and documented environment variables.

Database:

- Migration `0003_requests_alerts`: `card_requests`, `restock_alerts`,
  notification delivery columns (`recipient`, `attempts`, `next_attempt_at`),
  indexes, and RLS policies on both new tables.

### Vendor web admin

Pages:

| Route | Purpose |
| --- | --- |
| `/login` | Shop slug + email + password |
| `/` | Dashboard: pending holds, active holds, special orders, sold today, low/stale stock |
| `/stock` | Search, counts, price/visibility, adjustments, in-store sales, CSV import/export, waiting-demand badge |
| `/reservations` | Status queue, confirm/ready/cancel, partial completion |
| `/requests` | Special orders: quote, decline, convert to reservation |
| `/team` | Owner-only staff management |
| `/activity` | Owner-only audit trail |
| `/settings` | Branding, hold duration, payment instructions, contact, directory opt-in |

Colour-coded stock/status values always include a text label.

---

## 3. Verification status

| Check | Result |
| --- | --- |
| Backend SQLite suite | **87 passed** |
| Backend PostgreSQL suite (RLS, locking, migrations) | **7 passed** |
| Backend total with PostgreSQL env | **94 passed** |
| Backend Ruff / format / mypy | Clean |
| Admin ESLint / TypeScript / production build | Clean |
| Admin Playwright suite | **8 passed** |
| Root legacy `make check` | **268 passed** |
| Alembic upgrade → downgrade → upgrade | Verified on SQLite and PostgreSQL |
| RLS enabled + forced | All 10 tenant tables, including `card_requests` and `restock_alerts` |

Useful commands:

```bash
# Backend
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests
../.venv/bin/python -m pytest

# Admin
cd admin
npm run lint
npm run typecheck
npm run build
npm run test:e2e

# Legacy desktop
make check
```

PostgreSQL verification uses `backend/scripts/local_postgres.sh`; export the
admin and non-owner app URLs as described in `backend/README.md`.

CI already runs three workflows: legacy (`ci.yml`), backend (`backend.yml`),
and admin (`admin.yml`). The backend workflow includes the PostgreSQL suite,
migration round trip, and a per-table RLS assertion.

---

## 4. What needs to be done next

### Step 5 — customer mobile app (next)

The API surface for the customer journey already exists; the app is the missing
piece.

1. Scaffold `mobile/` with Expo + React Native + TypeScript, navigation,
   theming, and an API client generated from the OpenAPI snapshot.
2. Shop discovery, QR scan, and deep links into a shop.
3. Storefront: search, filters/facets, pagination, card detail, live
   availability.
4. Local cart, reservation form, confirmation with countdown, reservation
   list/detail, and cancel.
5. Restock alerts and the special-order flow: request, track, accept quote,
   cancel.
6. Customer OTP accounts and `/v1/me` endpoints; claim guest reservations and
   restock alerts when an account is created.
7. Push notifications (FCM/APNs) on top of the existing outbox.
8. Offline caching, error states, localization, and device E2E
   (Maestro/Detox), then pilot-shop onboarding.

### Pilot readiness (after the app)

- Onboard 1–2 real vendors and run manual billing.
- Configure a production SMTP provider; monitor delivery failures from the
  worker (`attempts`, `error`, `next_attempt_at`).
- Deployment runbook: managed PostgreSQL, backups, monitoring, and a non-owner
  app role.
- Move rate limiting to Redis if the API runs more than one worker.
- Decide whether converting a special order should apply the quoted price
  instead of the current shelf price (today the shelf price wins).
- Surface staff in-app notifications in the admin, or remove the unused
  in-app channel.

### Later roadmap

- Shop directory and theming polish across brands.
- Subscription automation, entitlements, and a platform-admin API.
- Raspberry Pi in-store node (optional, never the public server).
- Premium modules: online payments, shipping, white-label apps, more games.

---

## 5. Current limitations

- No customer mobile app yet; the platform is currently API + vendor admin.
- Guests only: no customer OTP accounts or `/v1/me` endpoints.
- Email notifications only; no push delivery and no staff notification inbox.
- Restock alerts are one-shot and email-based; they are not yet tied to
  customer accounts.
- Rate limiting is in-process, so it assumes a single API worker.
- Special-order quotes are informational; conversion holds stock at the current
  shelf price.
- Not in v1: online payments, shipping, tax, refunds, white-label apps,
  additional games, and Pi integration.
