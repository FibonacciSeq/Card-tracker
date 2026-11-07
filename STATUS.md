# Card Tracker platform — status

Last updated: **2026-11-07**
Latest commit: see `git log -1`
Working tree: account lifecycle/session-safety work and Scryfall market-based
stock pricing are implemented and verified. Shop Settings reprice existing
stock from catalog market prices when rules change; the nightly worker refreshes
prices and recalculates eligible stock. The local platform database contains
the Scryfall catalog required for stock imports. Step 5 is in release-readiness
work: finish offline/cache safety, validate production links and delivery, then
run a signed-in multi-device smoke before a small pilot.

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
  TanStack Query. The customer app is guest-first with an optional account
  session persisted in secure device storage and rotated by refresh token; types
  come from the same OpenAPI snapshot.
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
- ManaBox collection exports are also accepted. Header aliases, normal/foil
  finishes, and ManaBox condition names are normalized; distinct foil and
  nonfoil variants remain separate stock rows.
- Shop owners configure Scryfall pricing in Settings: prices below the minimum
  use the minimum, while prices at or above it receive the configured markup
  and round upward to a whole shop-currency unit.
- With automatic pricing enabled, stock imports use the Scryfall price for the
  matching finish; rows without a market price are skipped. The Scryfall
  pricing worker refreshes the catalog nightly at 02:00 UTC and recalculates
  existing shop stock from market data, never from its previous sale price.
  Shops using currencies without a matching Scryfall price use the latest
  published daily reference exchange rate.

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
- `/v1/me` profile, reservations, card requests, restock alerts, notification
  delivery rows, and push devices, including account-side cancel, quote accept,
  and alert deletion. The delivery log returns rendered titles only, and the
  push-device list exposes diagnostics without the raw token. Signing in claims
  unowned guest rows with the same email across shops; rows owned by another
  customer are never reassigned.
- Account access tokens are short-lived and paired with a rotated refresh token.
  The app persists both in secure device storage and rehydrates the session on
  cold launch. Logout sends the current device's refresh token so only that
  session is revoked; an empty logout body keeps the legacy account-wide
  revocation for older clients. `POST /v1/me/sessions/revoke-all` ends every
  active refresh session. Mobile provides **Sign out** and **Sign out all
  devices** with confirmation copy that matches the 12-hour access-token limit.
- Account deletion is a soft close: it deactivates the customer, revokes every
  refresh session, stops notification delivery, and keeps shop history with its
  tenants. The same email cannot sign in again without support, and device-local
  guest data remains. The full lifecycle matrix is in
  [`docs/product-decisions.md`](docs/product-decisions.md).
- Special-order quotes are explicitly indicative. Conversion creates the linked
  reservation at the stock row's current shelf price; customer and staff copy no
  longer implies a price lock.
- Email changes require an OTP sent to the new address. Verification rejects a
  target address already owned by another account, revokes existing refresh
  sessions, issues a fresh token pair to the current device, and claims unowned
  guest rows that use the new email.
- Global customer account/session events (login, refresh, logout, profile
  update, email change, deletion, and session revocation) are stored in
  `customer_audit_events`. The table is customer-scoped by PostgreSQL RLS and is
  deliberately separate from the tenant audit trail.
- The app combines `/v1/me` rows with device-local guest rows, preferring the
  account copy on duplicate IDs. Signed-in create forms lock the account email
  and still return a guest token for local detail.
- The signed-in `/notifications` screen shows per-channel delivery status,
  sanitized failures, active/revoked push devices, pull-to-refresh, and
  cursor-based load-more. It links back to Account for preference changes.
- Mobile checks: TypeScript, ESLint, Vitest logic coverage, `expo-doctor`,
  production web export, and a local browser smoke test through QR/manual entry,
  card detail, add-to-hold, restock subscribe/unsubscribe, special-order create,
  staff quote, and quote accept. Account/OTP/claim behavior is covered by
  backend SQLite and PostgreSQL tests.

The main Step 5 items are now implemented: push notifications, persisted
offline caching, locale support, mobile browser smoke coverage, account
lifecycle/session safety, account profile update/delete flows, and a customer
notification delivery log with push-device diagnostics. The remaining focus is
release QA, the signed-in multi-device smoke, and production app-link
validation. Printed codes still use the custom scheme, and universal links on a
public HTTPS domain are configured but not yet validated in production.

---

## 3. Verification status

| Check | Result |
| --- | --- |
| Root Python suite (`pytest --cov --cov-branch`) | **351 passed, 100% line/branch** |
| Backend SQLite suite | **265 passed, 13 PostgreSQL tests skipped, 100%** |
| Backend with PostgreSQL test URLs | **278 passed, 100%** (277 before the added per-device logout test) |
| Backend PostgreSQL-only suite (RLS, customer claiming, notifications, locking) | **13 passed** |
| Backend account/session tests | `tests/test_customer_accounts.py`: **22 passed**, including per-device logout |
| Backend Ruff lint / changed-file formatting / mypy | Clean |
| Alembic `0008_customer_notifications` downgrade → upgrade | Verified on SQLite and PostgreSQL; notification customer RLS policy and push diagnostics recreated; `alembic_version` widened to 64 chars |
| Admin ESLint / TypeScript / production build | Clean |
| Admin Vitest logic/API-client coverage | **23 passed, 100% statements/branches/functions/lines** |
| Admin production source maps | **0** `.map` files in `dist/` |
| Admin Playwright suite | **8 passed** |
| Generated API snapshot/types | `admin/openapi.json` and admin/mobile `schema.d.ts` regenerated; optional logout body present, no manual type edits |
| Mobile TypeScript / ESLint | Clean |
| Mobile Vitest `src/lib/**` coverage | **42 passed, 100% statements/branches/functions/lines** |
| Mobile `expo-doctor` | **20/20** |
| Mobile production web export | Passed |
| Mobile browser smoke test (local API) | Passed: scan entry → storefront → card detail → add to hold; restock subscribe/unsubscribe; special-order create → staff quote → customer accept |
| Mobile deep-link parser cases | Passed: custom scheme, https, Expo Go, path, slug, bad UUID, traversal, foreign scheme |
| SQL Server Docker schema/E2E | Wired in CI/Makefile; 21/21 assertions pass locally; skips cleanly without Docker |
| Alembic downgrade base → upgrade head | Verified on PostgreSQL |
| RLS enabled + forced | All 10 tenant tables, plus customer-scoped `push_tokens`, `customer_audit_events`, and customer-readable `notifications` |

Latest stock-import validation (2026-11-07):

- Scryfall-based stock pricing is configurable in Shop Settings and is applied
  to existing stock immediately when rules change, then refreshed nightly.
  Markups use Scryfall market prices as the baseline, so repricing does not
  compound the previous sale price.
- Existing catalog databases created before market prices were saved need one
  refresh from the Scryfall worker or a full default-cards import. The Settings
  save response now reports how many stock prices changed and how many rows
  lacked a finish-specific market price.
- Shop owners can configure the strict upward rounding increment in whole
  currency units. It defaults to 5 (prices advance to amounts ending in 0 or 5)
  and changing it immediately reprices existing eligible stock.
- Diagnosed the local database: all 120,045 catalog cards lacked stored market
  prices. Re-imported 120,042 cards with prices, then repriced 1,330 existing
  stock rows; 5 rows had no matching market price and retained their prior
  prices.
- Applied the new default 5-unit rounding to local stock: 455 prices changed;
  all 1,335 stock rows now use whole-currency prices divisible by 5.
- Backend SQLite suite passed with 100% statement and branch coverage; 13
  PostgreSQL-only tests were skipped because their test URLs were not
  configured. Backend Ruff lint, changed-file formatting, and mypy passed.
- Admin typecheck, lint, production build, and Vitest coverage passed after
  moving the pricing controls out of the stock-import panel: 23 tests and 100%
  statement, branch, function, and line coverage.
- Root cause of the “No catalog card” errors: the API database had only three
  catalog rows. Loaded the Scryfall default-cards dataset into the configured
  local API database (**120,042 cards**); `FRA` / `384` resolves to Plains.
- A stock-import dry run for `Plains,FRA,384` now reports one created row and no
  errors. The backend setup guide now makes loading the catalog into the same
  database used by the API a prerequisite.
- The uploaded `bulk.csv` parses as **1,332 rows with no parse or duplicate
  variant errors**. Stock was not changed during validation.
- `python3 -m pytest -q backend/tests`: passed; 13 PostgreSQL-only tests skipped
  because their test URLs were not configured.
- `python3 -m ruff check` on the changed backend files: passed.
- Alembic upgrade through `0009_stock_import_pricing`: passed on a temporary
  SQLite database; the new settings column was verified.
- Admin ESLint, TypeScript, Vitest (**23 passed**), and production build:
  passed.
- Admin Playwright smoke suite: **8 passed**, run on alternate port 5174
  because port 5173 was already occupied.
- The daily-rate provider returned a valid EUR/RSD quote for the current
  published date.

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
applies the URLs. Without those variables the SQLite run reports 13
PostgreSQL-test skips; with the local server and both URLs exported it reports
278 passed. CI supplies a real non-owner role.

CI runs four workflows: legacy (`ci.yml`), backend (`backend.yml`), admin
(`admin.yml`), and mobile (`mobile.yml`). The legacy workflow now includes the
root 100% branch-coverage gate and a disposable SQL Server job; the backend
workflow runs SQLite and PostgreSQL coverage, migration round trip, and a
per-table RLS assertion. Admin runs unit coverage, build, and Playwright; mobile
runs unit coverage, lint, typecheck, and the production web export.

---

## 4. What needs to be done next

### Step 5 — customer mobile app (mostly implemented)

The guest flow and optional OTP accounts are working, including QR/deep-link
entry, card detail, restock alerts, special orders, `/v1/me`, guest-row
claiming, and account profile update/deletion. The app also includes push
notification support, persisted query caching, locale selection, a
Playwright smoke check for the web build, signed-in session persistence with
refresh-token rotation, the customer notification preferences flow (display
name, phone, push/email toggles, quiet hours, and opt-out state), a signed-in
notification delivery log with active/revoked push-device diagnostics, and
public-storefront app links with a custom-scheme fallback.

Universal links and install flow are now configured around a canonical public
HTTPS app URL (`https://app.cardtracker.local` by default, overridable per
deployment), while the legacy `cardtracker://shop/...` scheme remains available
as a direct app fallback. The admin QR panel shows both so printed codes work
for customers who land in the browser and customers who already have the app
installed.

The current app work is in final QA/pilot-readiness polish rather than core
missing functionality. The notification-quality slice is implemented:
queued email/push deliveries honor a customer's opt-out, quiet hours, and
per-channel toggles, and the account now exposes per-channel delivery status,
sanitized failures, and push-token diagnostics. A disabled profile cannot
receive delivery while still keeping the rest of the flow intact.

Account lifecycle and special-order pricing decisions are closed as of
2026-11-07 in [`docs/product-decisions.md`](docs/product-decisions.md): logout
is per-device with an account-wide fallback for older clients, revoke-all ends
every session, delete is a documented soft close, and conversion uses the
current shelf price rather than the indicative quote. The next app task is
offline/cache safety.

### Recommended next steps — small, ordered tasks

Complete these in order. Each step has a concrete deliverable or pass condition;
do not begin a vendor pilot until the pre-pilot gates below pass.

1. Account lifecycle and session safety — **implemented 2026-11-07**
   - Refresh tokens rotate on use; logout revokes only this device when its
     refresh token is sent, while revoke-all ends every session.
   - Email changes require an OTP sent to the new address, reject addresses
     owned by another account, rotate sessions, and re-claim matching guest rows.
   - Account deletion is a documented soft close that revokes every session,
     stops delivery, and keeps shop history.
   - Customer audit rows cover logins, refreshes, profile updates, email changes,
     deletion, logout, and session revocation.
   - Acceptance met: behavior and customer-facing copy agree, and a revoked
     session cannot keep refreshing.

2. Account profile and notifications settings — **implemented**
   - Dedicated profile settings cover display name, phone, push/email toggles,
     quiet hours, and opt-out state.
   - Acceptance met: profile and preference changes stay consistent with account
     and guest-row claiming rules.

3. Universal links and install flow — **configured; production validation remains**
   - Canonical HTTPS app links and the custom-scheme fallback are wired through
     the admin QR panel and mobile parser.
   - Remaining production checks are split into steps 3.1–3.4 below.

4. Push/email notification quality — **implemented 2026-11-06**
   - `/v1/me/notifications` exposes per-channel delivery status, rendered
     titles, attempts, timestamps, and sanitized errors with cursor pagination.
   - `/v1/me/push-tokens` exposes active/revoked devices, failure counts, last
     failure time, and sanitized errors without returning the raw token.
   - The mobile notification screen shows the delivery log and device health,
     links back to preferences, and supports opt-out/re-enable flows.
   - Per-channel preferences, quiet hours, and opt-out were already implemented.
   - Acceptance met: a user can see notification status and safely opt out or
     re-enable delivery.

5. Offline and sync reliability — **mostly implemented**
   - Persisted query cache and account/guest merge are in place.
   - Remaining work: define how offline edits are handled and which cached
     account data must be invalidated after account changes; then add focused
     tests for those rules.

Implementation and QA task list (in order):

1. **Close product and account-UX decisions — implemented 2026-11-07**
   - 1.1 `docs/product-decisions.md` records sign-out, sign-out-everywhere,
     delete-account, email-change, and session-restoration behavior.
   - 1.2 Mobile uses confirmation modals with copy that matches the actual
     behavior; failure paths keep the session and show the error.
   - 1.3 Special-order conversion explicitly uses the current shelf price; the
     quote is documented and labelled as indicative in mobile and admin.
   - **Acceptance met:** behavior and customer-facing copy agree, and the
     pricing rule is explicit.

2. **Finish offline/cache safety**
   - 2.1 Document which screens are usable offline and which changes require a
     live connection.
   - 2.2 Define what happens when offline guest data overlaps with a signed-in
     account row; do not silently overwrite either copy.
   - 2.3 Check cache clearing/invalidation on sign-out, account switch, email
     change, account deletion, and successful guest-row claiming.
   - 2.4 Add or update tests for each rule, then run mobile lint, typecheck, and
     coverage.
   - **Done when:** stale account data cannot appear after identity changes,
     and offline edits have a predictable outcome.

3. **Prepare production app links and delivery**
   - 3.1 Choose and configure the public HTTPS app domain and hosting for the
     mobile web page and platform association files.
   - 3.2 Deploy the admin with `admin/public/_headers` (or equivalent CSP and
     security headers) enabled.
   - 3.3 Verify QR links and app links on a real Android and iOS device both
     with the app installed and from a fresh browser; record the tested URLs
     and results.
   - 3.4 Configure production SMTP and push-provider credentials; send and
     verify OTP, email, and push notifications, including opt-out behavior.
   - **Done when:** real-device links route correctly and the production
     notification path is exercised end to end.

4. **Run the signed-in multi-device smoke**
   - 4.1 Build/install the development app on two devices and sign into the
     same test customer account.
   - 4.2 Check session restore, refresh, sign-out, revoke-all, and email-change
     behavior across both devices.
   - 4.3 Check profile/preferences, notification history, push-device
     diagnostics, and one customer action visible across devices.
   - 4.4 Record failures, fix blockers, and repeat the failed cases.
   - **Done when:** both devices show consistent account state, revoked refresh
     sessions cannot refresh, and a deleted account is rejected on the next
     protected request.

5. **Complete pre-pilot operational checks**
   - 5.1 Run the PostgreSQL-only suite and migration round trip using the
     production-like non-owner application role.
   - 5.2 Confirm managed-database backups and a restore procedure; document
     deployment, rollback, and support contacts.
   - 5.3 Verify notification failures and retries can be inspected, and define
     who responds to a delivery or account-access incident.
   - **Done when:** the deployment has a tested recovery path and an owner for
     operational follow-up.

6. **Pilot with one shop, then expand**
   - 6.1 Onboard one vendor first; verify its owner login, stock setup, contact
     details, and notification settings.
   - 6.2 Complete an owner + customer test path: browse, reserve, process the
     reservation, cancel/complete as appropriate, and verify customer updates.
   - 6.3 Review issues and operational effort before onboarding a second shop;
     use manual billing during this limited pilot.
   - **Done when:** the first shop completes the end-to-end path without a
     tenant-isolation, data-loss, or severe customer-notification issue.

7. **Scale only after pilot evidence**
   - Add monitoring for notification failures, token expiration, and
     rate-limit events; review operational edge cases with pilot feedback.
   - Move in-process rate limiting to Redis before running multiple API workers.
   - Revisit staff in-app notifications only if pilot workflows require them;
     customer email and push remain the supported delivery channels today.
   - **Done when:** observed pilot needs are addressed and multi-worker behavior
     is deliberately supported before scaling.

### Later roadmap

- Shop directory and theming polish across brands.
- Subscription automation, entitlements, and a platform-admin API.
- Raspberry Pi in-store node (optional, never the public server).
- Premium modules: online payments, shipping, white-label apps, more games.

---

## 5. Current limitations

- Customer accounts are optional and OTP-only. The backend issues rotating
  refresh tokens, supports per-device logout and revoke-all session actions,
  requires an OTP to the new address before changing email, and writes
  customer-scoped account audit rows. The mobile app persists and rehydrates the
  session across app restarts. A customer-facing audit/activity screen is not
  exposed yet.
- Sign-out and revoke-all stop refresh immediately but cannot invalidate an
  already-issued access JWT before its 12-hour expiry. Deleting or deactivating
  the account is enforced on the next request because `is_active` is checked.
- Delete account is a soft close, not a full erasure: the customer row,
  profile, audit rows, and shop history are retained, while delivery stops and
  every session is revoked. A support-assisted erasure process is still needed
  for full data-deletion requests.
- Guest rows are still device-local until a customer verifies the same email.
  Push delivery, persisted offline caching, localization, and browser smoke
  coverage are implemented. Offline conflict/cache invalidation rules and the
  signed-in native multi-device smoke remain to be completed before pilot.
- Printed QR codes can use the canonical HTTPS public app URL and still fall
  back to the `cardtracker://` custom scheme, but production domain
  configuration and app-store install paths still need final deploy-time setup.
- Notification delivery is gated by customer preferences at the worker level,
  so email and push respect opt-out, quiet hours, and per-channel toggles. The
  customer delivery log is per-channel: one business event can appear as a
  separate email and push entry. It returns rendered titles but deliberately
  omits message bodies so unsubscribe tokens do not leak.
- Push-device diagnostics show the last sanitized error and failure count on the
  token, and invalid provider tokens are revoked automatically. A customer can
  re-enable delivery by registering the device again.
- Restock alerts are one-shot and email-based. They can be linked to a customer
  account or claimed later, and the links now prefer the canonical public app
  URL while remaining compatible with the custom-scheme fallback.
- OTP and guest-create rate limiting is in-process, so it assumes a single API
  worker; the per-email challenge cooldown is also database-backed.
- The PostgreSQL-only tests skip locally unless the two test URLs are set;
  SQLite cannot exercise RLS, row locking, or the last-copy race.
- The admin static host must serve the CSP/security headers from
  `admin/public/_headers`; Vite only applies them in dev/preview.
- On web, the mobile preview stores guest tokens in AsyncStorage because
  SecureStore has no web implementation; native builds use SecureStore.
- Special-order quotes are explicitly indicative, not price locks; conversion
  holds stock at the stock row's current shelf price. This is documented in
  `docs/product-decisions.md` and reflected in mobile and admin copy. Price
  locks remain a possible post-pilot feature.
- Not in v1: online payments, shipping, tax, refunds, white-label apps,
  additional games, and Pi integration.
