# Card Tracker platform — status

Last updated: **2026-10-29**
Latest commit: **`b05107c` — Add restock alerts and special-order customer flows**
Working tree: Step 5 optional customer accounts/OTP, `/v1/me`, automatic guest
claiming, and the 100% coverage/CI hardening (uncommitted at the time of writing)

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
| Multi-vendor platform API | `backend/` | Implemented through Step 4 + audit hardening, plus Step 5 accounts |
| Vendor web admin | `admin/` | Implemented through Step 4 + audit hardening |
| Customer mobile app | `mobile/` | Guest vertical slice plus optional OTP accounts (Step 5 in progress) |

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
  TanStack Query. The customer app is guest-first with an optional
  memory-only account session; types come from the same OpenAPI snapshot.
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
  The app now also uses a signed, tenant/alert-scoped token, with an HTML
  confirmation page and an RFC 8058 one-click endpoint for email clients.
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
| `/settings` | Branding, hold duration, payment instructions, contact, directory opt-in, printable shop QR |

Colour-coded stock/status values always include a text label. The production
bundle has no source maps; `admin/public/_headers` supplies CSP and browser
security headers. Client logging is development-only and records sanitized
error metadata (type/status), never request bodies or tokens.

### Step 5 — customer mobile app and optional accounts (2026-10-29)

The customer app now exists as a working guest vertical slice, with optional
email-OTP accounts on top:

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
- Dedicated card-detail route with a large image, price, live availability,
  variant metadata, add-to-hold controls, and a link back to the shop.
- In-store QR entry: `expo-camera` scans shop and card codes, with manual
  shop-code entry as the fallback on web and when the camera is unavailable.
- Deep links `cardtracker://shop/<slug>` and
  `cardtracker://shop/<slug>/card/<stock-id>` open the same routes on cold start
  or while running. The parser also accepts the equivalent `https` path, Expo Go
  `exp://…/--/…` links, a bare path, or a slug, and rejects other schemes/paths.
- The vendor admin renders the shop QR code (and copy/download actions) from
  **Settings**, entirely in the browser.
- Sold-out card detail offers a single-opt-in restock alert. Alerts have a
  dedicated list screen and can be removed with a signed manage token.
- Restock emails contain a card deep link, an unsubscribe link, and RFC 8058
  `List-Unsubscribe` / `List-Unsubscribe-Post` headers. Unsubscribe works from
  the app, an HTML confirmation page, or a one-click POST.
- Special-order request form, local request list, live status detail, quote
  accept, and cancel. The guest request token is stored in SecureStore.
- Optional global customer account per verified email, with 6-digit email OTP
  sign-in. The API stores only an HMAC-derived code/challenge, not plaintext,
  and the notification worker delivers the code through the existing outbox.
- `/v1/me` profile, reservations, card requests, and restock alerts, including
  account-side cancel, quote accept, and alert deletion. Signing in claims
  unowned guest rows with the same email across shops; rows owned by another
  customer are never reassigned.
- Account token is 12 hours and memory-only in the app: cold launch starts
  signed out, while background resume keeps the session until expiry. There is
  no refresh or revocation yet.
- The app combines `/v1/me` rows with device-local guest rows, preferring the
  account copy on duplicate IDs. Signed-in create forms lock the account email
  and still return a guest token for local detail.
- Mobile checks: TypeScript, ESLint, Vitest logic coverage, production web
  export, and a local browser smoke test through QR/manual entry, card detail,
  add-to-hold, restock subscribe/unsubscribe, special-order create, staff
  quote, and quote accept. Account/OTP/claim behavior is covered by backend
  SQLite and PostgreSQL tests.

Still missing from Step 5: push notifications, offline caching, localization,
device E2E, and account profile editing/email change/deletion or
refresh/revocation. Unowned guest rows stay device-local until that email is
verified; a signed-in multi-device browser smoke is still a release check.
Printed codes use the custom scheme; universal links on a public HTTPS domain
are not configured yet.

---

## 3. Verification status

| Check | Result |
| --- | --- |
| Root Python suite (`pytest --cov --cov-branch`) | **351 passed, 100% line/branch** |
| Backend SQLite suite | **209 passed, 10 PostgreSQL tests skipped, 100%** |
| Backend with PostgreSQL test URLs | **219 passed, 100%** |
| Backend PostgreSQL-only suite (RLS, customer claiming, locking) | **10 passed** |
| Backend Ruff / format / mypy | Clean |
| Alembic `0004_customer_accounts` downgrade → upgrade | Verified on PostgreSQL; indexes and RLS policies recreated |
| Admin ESLint / TypeScript / production build | Clean |
| Admin Vitest logic/API-client coverage | **23 passed, 100% statements/branches/functions/lines** |
| Admin production source maps | **0** `.map` files in `dist/` |
| Admin Playwright suite | **8 passed** |
| Mobile TypeScript / ESLint | Clean |
| Mobile Vitest `src/lib/**` coverage | **26 passed, 100% statements/branches/functions/lines** |
| Mobile `expo-doctor` | **20/20** |
| Mobile production web export | Passed |
| Mobile browser smoke test (local API) | Passed: scan entry → storefront → card detail → add to hold; restock subscribe/unsubscribe; special-order create → staff quote → customer accept |
| Mobile deep-link parser cases | Passed: custom scheme, https, Expo Go, path, slug, bad UUID, traversal, foreign scheme |
| SQL Server Docker schema/E2E | Wired in CI/Makefile; 21/21 assertions pass locally; skips cleanly without Docker |
| Alembic downgrade base → upgrade head | Verified on PostgreSQL |
| RLS enabled + forced | All 10 tenant tables, including `card_requests` and `restock_alerts` |

The Python coverage floors are 100% line and branch for both the root and
backend suites. Admin and mobile keep their explicitly included logic/API
client modules at 100%; admin screens are covered by Playwright rather than
line instrumentation. SQLite and PostgreSQL both reach the backend gate.

Useful commands:

```bash
# Root legacy desktop app + coverage
make check
make cov
make test-all           # full matrix (root/backend/admin/mobile/Postgres/SQL Server)
make test-matrix        # tox over installed Python interpreters (uv can install them)

# Backend
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests
../.venv/bin/python -m pytest --cov=app --cov-branch --cov-report=term-missing
./scripts/test_backend_postgres.sh  # from the repository root

# Admin
cd admin
npm run lint
npm run typecheck
npm run test:coverage
npm run build
find dist -name '*.map'      # must print nothing
npm run test:e2e

# Mobile
cd mobile
npm run lint
npm run typecheck
npm run test:coverage
npm run export:web
npm run doctor
```

PostgreSQL verification uses `backend/scripts/local_postgres.sh`; export the
admin and non-owner app URLs as described in `backend/README.md`, or use
`./scripts/test_backend_postgres.sh`, which starts the portable server and
applies the URLs. Without those variables the SQLite run reports 10
PostgreSQL-test skips; with the local server and both URLs exported it reports
219 passed. CI supplies a real non-owner role.

CI runs four workflows: legacy (`ci.yml`), backend (`backend.yml`), admin
(`admin.yml`), and mobile (`mobile.yml`). The legacy workflow now includes the
root 100% branch-coverage gate and a disposable SQL Server job; the backend
workflow runs SQLite and PostgreSQL coverage, migration round trip, and a
per-table RLS assertion. Admin runs unit coverage, build, and Playwright; mobile
runs unit coverage, lint, typecheck, and the production web export.

---

## 4. What needs to be done next

### Step 5 — customer mobile app (in progress)

The guest flow and optional OTP accounts are working, including QR/deep-link
entry, card detail, restock alerts, special orders, `/v1/me`, and guest-row
claiming. The remaining app work, in order:

1. Add push notifications (FCM/APNs) on top of the existing outbox.
2. Add offline caching, localization, and device E2E (Maestro/Detox), then
   pilot-shop onboarding.
3. Run a signed-in multi-device smoke on a development build and decide on
   account refresh/revocation and optional profile management.

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
- Configure universal/app links (`https://…/shop/…`) on the production domain
  before printing QR codes at scale; today's codes use `cardtracker://`.
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

- Customer accounts are optional and OTP-only; there is no password, refresh
  token, revocation/session list, profile editing, email change, or deletion
  yet. The account token is memory-only in the app, so a cold launch requires
  a new code.
- Guest rows are still device-local until a customer verifies the same email.
  There is no push delivery, offline cache, or device E2E yet.
- Printed QR codes use the `cardtracker://` custom scheme. Universal/app links
  on a public HTTPS domain are not configured, and app-store fallback for
  customers without the app is not implemented yet.
- Email notifications only; no push delivery and no staff notification inbox.
- Restock alerts are one-shot and email-based. They can be linked to a customer
  account or claimed later, but the card link in those emails uses the custom
  scheme until universal links are configured.
- OTP and guest-create rate limiting is in-process, so it assumes a single API
  worker; the per-email challenge cooldown is also database-backed.
- The PostgreSQL-only tests skip locally unless the two test URLs are set;
  SQLite cannot exercise RLS, row locking, or the last-copy race.
- The admin static host must serve the CSP/security headers from
  `admin/public/_headers`; Vite only applies them in dev/preview.
- On web, the mobile preview stores guest tokens in AsyncStorage because
  SecureStore has no web implementation; native builds use SecureStore.
- Special-order quotes are informational; conversion holds stock at the current
  shelf price.
- Not in v1: online payments, shipping, tax, refunds, white-label apps,
  additional games, and Pi integration.
