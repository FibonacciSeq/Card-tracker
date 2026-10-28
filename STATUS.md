# Card Tracker platform — status

Last updated: **2026-10-28**
Latest feature commit: **`e0c4d10` — Add restock alerts, special orders, and notification delivery**
Working tree: post-Step-4 audit hardening and the Step 5 customer guest slice (uncommitted at the time of writing)

This file is the quick, human-readable status of the multi-vendor platform.
The full product/technical specification lives outside the repository in the
project plan; this document records what is actually implemented, how it is
verified, and what comes next.

---

## 1. What this repository contains

The repository currently holds the legacy desktop app and the platform
client/server stack side by side:

| Part | Location | Status |
| --- | --- | --- |
| Legacy Tkinter desktop shop (customer + owner + collection tool) | root `*.py`, `ui/`, `services/`, `database/` | Working; kept unchanged as a fallback |
| Multi-vendor platform API | `backend/` | Implemented through Step 4 + audit hardening |
| Vendor web admin | `admin/` | Implemented through Step 4 + audit hardening |
| Customer mobile app | `mobile/` | Guest vertical slice implemented (Step 5 in progress) |

The platform is the forward path: one cloud API and one admin codebase serving
many shops, with a native customer app on top. The legacy desktop app remains
for the original single-shop workflow until the new stack replaces it.

### Architecture at a glance

- **API:** FastAPI + SQLAlchemy 2 + Pydantic v2 + Alembic, PostgreSQL in
  production (SQLite for fast local tests).
- **Tenancy:** every tenant-owned row carries `tenant_id`; PostgreSQL RLS is
  enabled and forced. Compose runs migrations as the schema owner and the API
  and workers as a separate non-owner/non-superuser role. Tenant context is a
  transaction-local `app.tenant_id` setting, re-applied after commits.
- **Money:** integer minor units plus ISO currency code. No floats.
- **Admin:** Vite + React 19 + TypeScript + TanStack Query, no SSR and no
  second backend. Types are generated from a committed OpenAPI snapshot.
- **Mobile:** Expo SDK 58 + React Native + TypeScript + Expo Router +
  TanStack Query. The customer app is a guest-first slice; types come from the
  same OpenAPI snapshot.
- **Workers:** expiry worker (holds and quotes) and notification outbox worker.
- **Notifications:** transactional outbox with console or SMTP delivery,
  retry/backoff, and per-tenant iteration so RLS stays enforced. The `none`
  backend deliberately leaves the outbox untouched instead of dropping mail.

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
- Idempotent subscribe; unsubscribe with alert id + email in a JSON body
  (always returns 204, and never puts the address in a URL).
- One-shot `notified_at`; alerts fire when a variant returns to stock via
  create, update, manual adjust, CSV import, an offline → online toggle, or a
  reservation release.
- No notification while stock is offline or still unavailable.
- Alert rows are locked while being claimed so parallel stock changes do not
  double-send. A permanently failed delivery releases the alert for a later
  restock attempt.
- Admin stock rows show a “N waiting” demand badge.

Special orders:

- Guest create/track/accept quote/cancel with a per-request access token.
- Statuses: `REQUESTED → QUOTED → ACCEPTED → CONVERTED`, plus `DECLINED`,
  `EXPIRED`, `CANCELLED`.
- Staff queue with quote (price, optional expiry, note), decline, and convert.
- A quote cannot be created with an expiry in the past. Accepting an expired
  quote moves it to `EXPIRED` and notifies the customer.
- Staff can decline an `ACCEPTED` request; abandoned `ACCEPTED` requests expire
  after 14 days.
- Conversion requires the exact catalog card and variant in stock, creates a
  linked `CONFIRMED` reservation, and holds stock immediately.
- Stale quotes expire automatically in the expiry worker.

Notifications:

- Outbox delivery worker iterating tenants to satisfy RLS.
- `console` (default) and `smtp` backends using the standard library; `none`
  disables delivery without marking queued mail as sent.
- Console output is redacted to the rendered subject; recipients, bodies, and
  customer details are not written to logs. Failed deliveries store only the
  exception type/SMTP code.
- Retry with 60 s doubling backoff, capped at one hour, default 8 attempts.
- Customer and staff emails for reservation create/ready/cancel/expire/complete,
  quote/decline/accept, conversion, and restock events. Staff alerts fall back
  to the public contact email when `notification_email` is unset.
- Docker Compose `notifications` worker and documented environment variables.

Database:

- Migration `0003_requests_alerts`: `card_requests`, `restock_alerts`,
  notification delivery columns (`recipient`, `attempts`, `next_attempt_at`),
  indexes, and RLS policies on both new tables.

### Audit hardening — 2026-10-28

Correctness and security fixes applied after the first platform audit:

- Price, newest, and name cursors now use a composite `(sort value, id)`
  keyset cursor with a stable tie-breaker, so pagination cannot skip or repeat
  rows when prices/names collide.
- Invalid request payloads return 422 errors with only `type`, `loc`, and
  `msg`; FastAPI's default `input`/`ctx` fields are stripped so a mistyped
  password is never echoed in the response or browser devtools.
- Guest reservation idempotency tokens are derived with HMAC from the
  idempotency key. New idempotency rows store only the reservation id, never a
  usable guest credential; expired keys are pruned on the next create.
- Restock unsubscribe moved from `DELETE ...?email=...` to
  `POST .../unsubscribe` with a JSON body, keeping addresses out of URL logs.
- Reservation expiry, customer cancellation, and completion now enqueue
  customer email notifications; staff recipients fall back to the public
  contact address.
- Restock alerts now also fire on offline → online and reservation release,
  and permanent delivery failure clears the one-shot marker.
- Special orders reject past quote expiries, notify when an expired quote is
  accepted, allow staff to decline `ACCEPTED` requests, and expire abandoned
  accepted requests after 14 days.
- New stock rows must use the shop currency and a 2–5 letter language code.
- Demo seed sets tenant context before inserting tenant-owned rows and sets a
  default `notification_email`.
- Compose creates a non-owner `cardtracker_app` role; migrations run as the
  schema owner through `CARDTRACKER_MIGRATION_DATABASE_URL`.
- Admin production bundles no longer include source maps; CSP and security
  headers are in `admin/public/_headers` and Vite dev/preview. The client logs
  only sanitized error type/status in development, has a render error boundary
  and global error handlers, and the queue/dashboard poll every 20 seconds.
- The admin transition map no longer offers the invalid
  `REQUESTED → READY` jump.

### Vendor web admin

Pages:

| Route | Purpose |
| --- | --- |
| `/login` | Shop slug + email + password |
| `/` | Dashboard: pending holds, active holds, special orders, sold today, low/stale stock |
| `/stock` | Search, counts, price/visibility, adjustments, in-store sales, CSV import/export, waiting-demand badge |
| `/reservations` | Status queue, confirm/ready/cancel, partial completion; auto-refreshes every 20 s |
| `/requests` | Special orders: quote, decline, convert to reservation |
| `/team` | Owner-only staff management |
| `/activity` | Owner-only audit trail |
| `/settings` | Branding, hold duration, payment instructions, contact, directory opt-in |

Colour-coded stock/status values always include a text label. The production
bundle has no source maps; `admin/public/_headers` supplies CSP and browser
security headers. Client logging is development-only and records sanitized
error metadata (type/status), never request bodies or tokens.

### Step 5 — customer mobile guest slice (2026-10-28)

The customer app now exists as a working guest vertical slice:

- Expo SDK 58 + React Native + TypeScript + Expo Router, with a generated API
  types snapshot and TanStack Query hooks.
- Shop directory with search and pull-to-refresh.
- Storefront with live stock, search, sort, availability filter, and
  cursor-based load-more pagination.
- Per-shop local cart persisted on the device.
- Guest reservation form, idempotent submission, confirmation with countdown,
  local hold history, detail refresh, and cancellation.
- Guest reservation tokens use SecureStore on native platforms; the web
  preview falls back to AsyncStorage.
- `cardtracker://` scheme configured for future QR and deep links.
- Mobile checks: TypeScript, ESLint, production web export, and a local
  browser smoke test through the full guest hold flow.

Still missing from Step 5: QR scanning/deep-link entry, a dedicated card-detail
route, restock-alert and special-order screens, customer accounts/OTP,
`/v1/me`, push notifications, offline caching, localization, and device E2E.

---

## 3. Verification status

| Check | Result |
| --- | --- |
| Backend SQLite suite | **99 passed, 7 skipped** |
| Backend with PostgreSQL test URLs | **106 passed** |
| Backend PostgreSQL-only suite (RLS, locking) | **7 passed** |
| Backend Ruff / format / mypy | Clean |
| Admin ESLint / TypeScript / production build | Clean |
| Admin production source maps | **0** `.map` files in `dist/` |
| Admin Playwright suite | **8 passed** |
| Mobile TypeScript / ESLint | Clean |
| Mobile `expo-doctor` | **20/20** |
| Mobile production web export | Passed |
| Mobile browser smoke test (local API) | Passed: directory → storefront → hold → cancel |
| Root legacy `make check` | **268 passed** |
| Alembic downgrade base → upgrade head | Verified on PostgreSQL |
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
find dist -name '*.map'      # must print nothing
npm run test:e2e

# Mobile
cd mobile
npm run lint
npm run typecheck
npm run export:web

# Legacy desktop
make check
```

PostgreSQL verification uses `backend/scripts/local_postgres.sh`; export the
admin and non-owner app URLs as described in `backend/README.md`. Without
those variables the SQLite run reports 7 skips; with the local server and both
URLs exported it reports 106 passed. CI supplies a real non-owner role.

CI already runs four workflows: legacy (`ci.yml`), backend (`backend.yml`),
admin (`admin.yml`), and mobile (`mobile.yml`). The backend workflow includes
the PostgreSQL suite, migration round trip, and a per-table RLS assertion. The
mobile workflow runs lint, typecheck, and the production web export.

---

## 4. What needs to be done next

### Step 5 — customer mobile app (in progress)

The guest vertical slice is working. The remaining app work, in order:

1. Add QR scanning/deep-link entry and a dedicated card-detail route.
2. Add the restock-alert UI and special-order flow: request, track, accept
   quote, cancel.
3. Add customer OTP accounts and `/v1/me` endpoints; claim guest reservations
   and restock alerts when an account is created.
4. Add push notifications (FCM/APNs) on top of the existing outbox.
5. Add offline caching, localization, and device E2E (Maestro/Detox), then
   pilot-shop onboarding.

### Pilot readiness (after the app)

- Onboard 1–2 real vendors and run manual billing.
- Configure a production SMTP provider; monitor delivery failures from the
  worker (`attempts`, `error`, `next_attempt_at`).
- Deployment runbook: managed PostgreSQL, backups, monitoring, and the
  owner/migration vs non-owner application role split already wired into
  Compose.
- Apply `admin/public/_headers` (or equivalent CSP/security headers) at the
  production static host; the Vite headers only cover dev/preview.
- Run the PostgreSQL-only suite against the production-like database role and
  migration round trip before onboarding.
- Move rate limiting to Redis if the API runs more than one worker.
- Decide whether converting a special order should apply the quoted price
  instead of the current shelf price (today the shelf price wins).
- Surface staff in-app notifications in the admin, or remove the unused
  in-app channel; customer email is the only external channel today.

### Later roadmap

- Shop directory and theming polish across brands.
- Subscription automation, entitlements, and a platform-admin API.
- Raspberry Pi in-store node (optional, never the public server).
- Premium modules: online payments, shipping, white-label apps, more games.

---

## 5. Current limitations

- Customer app is a guest-only vertical slice; there is no account screen,
  push delivery, restock-alert UI, special-order UI, QR scanner, offline cache,
  or device E2E yet.
- Guests only: no customer OTP accounts or `/v1/me` endpoints.
- Email notifications only; no push delivery and no staff notification inbox.
- Restock alerts are one-shot and email-based; they are not yet tied to
  customer accounts.
- The PostgreSQL-only tests skip locally unless the two test URLs are set;
  SQLite cannot exercise RLS, row locking, or the last-copy race.
- The admin static host must serve the CSP/security headers from
  `admin/public/_headers`; Vite only applies them in dev/preview.
- On web, the mobile preview stores guest tokens in AsyncStorage because
  SecureStore has no web implementation; native builds use SecureStore.
- Rate limiting is in-process, so it assumes a single API worker.
- Special-order quotes are informational; conversion holds stock at the current
  shelf price.
- Not in v1: online payments, shipping, tax, refunds, white-label apps,
  additional games, and Pi integration.
