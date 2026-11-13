# Card Tracker platform — status

Last updated: **2026-11-13**
Latest commit: see `git log -1`
Working tree: customer password authentication, a forced mobile sign-in gate,
and email authenticity checks; owner/staff in-app notification inbox,
account lifecycle/session-safety work,
offline/cache safety, Scryfall market-based stock pricing, and stock archiving
are implemented and verified. Customers sign in with email + password; OTP
codes are reserved for signup verification, password reset, and email change.
All business-event updates are in-app notifications plus optional push for
signed-in customers, and owners/staff get a per-user inbox in the admin app.
No staff alert emails or guest customer deliveries are sent. Shop Settings reprice existing stock from catalog market prices when
rules change; the nightly worker refreshes prices and recalculates eligible
stock. Staff can archive all stock for a shop in one action, inspect it in a
separate archived view, restore it manually or by importing a matching card
again, permanently delete individual archived cards or the whole archive, and
set an automatic retention period for archived stock. Admin reservation and
special-order views now show catalog card thumbnails so staff can identify a
card at a glance. The local platform database contains the Scryfall catalog
required for stock imports. Step 5 is in
release-readiness work: validate production links and delivery, then run a
signed-in multi-device smoke before a small pilot.

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
| Customer mobile app | `mobile/` | Password accounts with forced sign-in (Step 5 in progress) |

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
  TanStack Query. The customer app requires a password sign-in before any shop,
  cart, hold, or account screen opens. The session is persisted in secure device
  storage and rotated by refresh token; types come from the same OpenAPI
  snapshot.
- **Workers:** expiry worker (holds and quotes) and notification outbox worker.
- **Notifications:** transactional outbox with console or SMTP delivery for
  account-security OTP codes plus push delivery; business-event updates are
  in-app rows in the customer feed. Owners/staff get a per-user admin inbox for
  new reservations, customer cancellations/expiry, and special-order activity.
  Retry/backoff and per-tenant iteration keep RLS enforced. The `none` backend
  deliberately leaves the outbox untouched instead of dropping mail.

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

### Stock archiving — 2026-11-08

- Staff can archive every active stock row for the current shop with
  **Archive all stock** in the admin. Rows are soft-archived with
  `stock.archived_at`, so reservation lines, stock movements, and history keep
  their foreign keys.
- Archived rows disappear from the active admin stock list, the public
  storefront (list, detail, facets, and search), new customer and staff holds,
  special-order conversion, restock alerts, Scryfall repricing, dashboard
  low/stale counts, and the default CSV export.
- The admin has a separate **Archived** stock tab with a per-row **Restore**
  action. The API exposes `GET /v1/staff/stock?archived=true` and
  `GET /v1/staff/stock/export.csv?archived=true`.
- Re-importing the same card and variant through CSV, or creating it through
  the staff stock API, automatically clears `archived_at` and restores the
  existing row instead of rejecting it as a duplicate. A restore is refused if
  the new quantity would fall below the row's reserved copies.
- Existing reservations remain valid. Completion and cancellation can still
  change archived rows, and the archive response reports how many reserved
  copies remain held. New holds treat archived stock as unavailable.
- Archiving does not change `is_online`; restoring a row preserves its previous
  visibility setting. Audit actions are `stock.archive_all` and
  `stock.restore`.
- Migration `0011_stock_archive` adds `stock.archived_at` and the
  `(tenant_id, archived_at)` index.

### Archive deletion and retention — 2026-11-09

- The archived tab can permanently delete one card (**Delete**, with an inline
  confirmation) or the whole archive (**Delete all archived**, with a
  confirmation panel). Deletion only ever targets rows that are already
  archived; active stock is never touched.
- `DELETE /v1/staff/stock/{stock_id}` removes one archived row and
  `DELETE /v1/staff/stock/archive` removes every eligible archived row for the
  shop. Both are tenant-scoped and audited as `stock.delete` /
  `stock.delete_all`.
- Rows with an active customer hold (`stock.reserved > 0` or an open
  reservation line with remaining quantity) are kept. Bulk deletion reports
  how many rows were deleted and how many were kept; the single-row action
  returns `409` for a held row. Rows become eligible once their reservations
  close.
- Reservation history survives deletion. `reservation_lines.stock_id` is now
  nullable with `ON DELETE SET NULL`, so completed/cancelled reservations keep
  their card, price, and quantity snapshots. Stock movements and restock alerts
  for the deleted stock row are removed/detached by their existing foreign
  keys.
- Shop Settings has an **Archived stock** field: delete archived cards after a
  number of days (`0` keeps them forever, maximum 3650). The 60-second expiry
  worker purges expired archived rows for every shop, and listing the archived
  tab performs the same purge lazily so local API-only setups stay consistent.
  Automatic purges are audited as `stock.delete_expired`.
- Migration `0012_archive_retention` adds
  `tenant_settings.archive_retention_days` (with a validation check) and makes
  `reservation_lines.stock_id` nullable with `ON DELETE SET NULL`.
  Downgrading removes detached reservation lines because the older schema
  cannot represent them.

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
| `/stock` | Search, counts, price/visibility, adjustments, in-store sales, CSV import/export, archive-all, archived-view restore/delete, retention-aware archived view, waiting-demand badge |
| `/reservations` | Status queue, confirm/ready/cancel, partial completion; auto-refreshes every 20 s |
| `/requests` | Special orders: quote, decline, convert to reservation |
| `/team` | Owner-only staff management |
| `/activity` | Owner-only audit trail |
| `/settings` | Branding, hold duration, payment instructions, contact, directory opt-in, printable shop QR |

Colour-coded stock/status values always include a text label. The production
bundle has no source maps; `admin/public/_headers` supplies CSP and browser
security headers. Client logging is development-only and records sanitized
error metadata (type/status), never request bodies or tokens.

### Step 5 — customer mobile app and password accounts (2026-10-29)

The customer app now exists as a working vertical slice behind a mandatory
email + password sign-in:

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
- Global customer account per verified email, secured by a password. New
  customers verify ownership of the email with a six-digit OTP, then choose a
  password; returning customers sign in with email + password. The API stores
  the code as an HMAC-derived challenge, never plaintext, and the notification
  worker delivers signup, reset, and email-change codes through the existing
  outbox. `CustomerOut.has_password` tells the app whether a password is set
  without exposing the hash.
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
  production web export, and a local browser smoke test that confirms the forced
  sign-in gate, the sign-in screen, protected-route redirects, and the locale
  toggle, plus authenticated QR/manual entry, card detail, add-to-hold, restock
  subscribe/unsubscribe, special-order create, staff quote, and quote accept.
  Password signup/login/reset, account/OTP/claim behavior, and session safety
  are covered by backend SQLite and PostgreSQL tests.

The main Step 5 items are now implemented: push notifications, persisted
offline caching, locale support, mobile browser smoke coverage, account
lifecycle/session safety, account profile update/delete flows, and a customer
notification delivery log with push-device diagnostics. The remaining focus is
release QA, the signed-in multi-device smoke, and production app-link
validation. Printed codes still use the custom scheme, and universal links on a
public HTTPS domain are configured but not yet validated in production.

### Card thumbnails in admin reservations and special orders — 2026-11-12

- Admin reservation details show a thumbnail on every card line, in both the
  read-only list and the complete-at-counter table. Special orders show the
  linked catalog card's thumbnail in the queue row and the quote/decline/convert
  panel.
- Reservation line and card-request responses now carry `image_small` and
  `image_normal` from the catalog card. The card request keeps the image nullable
  for free-text requests that have no catalog card.
- The quote form hint now says the customer is notified in the app instead of
  being emailed, matching the OTP-only email flow.

### Notification rework — email is OTP-only — 2026-11-12

- Business events no longer send email. Email is reserved for account-security
  OTP codes: customer signup verification, password reset, and email-change
  verification. Everyday customer sign-in uses a password and sends no email.
- Customer event notifications — reservation status changes, quote
  quoted/declined/expired/converted, and restock available — are in-app rows in
  the signed-in customer feed plus a push row when the customer allows push.
  In-app rows are marked sent at creation (the feed is the delivery), so the
  worker only drains OTP email and push rows.
- Staff alert emails are gone: `RESERVATION_CREATED`,
  `CARD_REQUEST_CREATED`, and `CARD_REQUEST_ACCEPTED` no longer send email. The
  admin dashboard and queues cover those events. The "Reservation alert email"
  setting was removed from the staff settings API and the admin Settings page;
  the database column stays for compatibility.
- Guest customers receive no customer notifications: event notifications
  enqueue only when a customer account owns the row. Staff still get admin-inbox
  rows for guest reservations and requests. Guest restock alerts stay pending
  rather than being marked notified, so they are claimed — and fire on the next
  restock — once the same email signs in.
- Mobile copy follows the change: restock alerts say "notify" instead of
  "email", guests are pointed at sign-in, the email preference toggle was
  removed from Account (the API field stays for compatibility), and the
  notifications screen describes push and in-app delivery. SQLite and
  PostgreSQL suites cover both customer and guest paths at 100% coverage.

### Owner/staff notification inbox — 2026-11-13

- Staff notifications reuse the existing `notifications` table with one
  `channel="in_app"` row per active owner/staff account, so each team member has
  their own read state. No migration or new audience column was needed.
- The inbox is queued inside the business transaction for: new customer
  reservations, customer-cancelled reservations, expired holds, new special
  orders, customer-accepted quotes, and customer-cancelled special orders.
  Actions taken by staff themselves do not notify staff.
- `GET /v1/staff/notifications` returns rendered titles/bodies, the action link,
  cursor pagination, and the unread count. `POST /v1/staff/notifications/{id}/read`
  and `POST /v1/staff/notifications/read-all` clear unread state with tenant and
  user filtering.
- The admin app has a Notifications page and nav entry with an unread badge. The
  badge and list poll every 20 seconds; read-all is idempotent.
- Backend coverage includes rendering for every staff event kind, pagination,
  unread counts, tenant/user isolation, inactive-staff filtering, and event
  enqueue paths for reservations, expiry, and special orders.

### Customer passwords and forced sign-in — 2026-11-13

- Customer accounts now use email + password for sign-in. `POST /v1/auth/login`
  verifies the stored password hash and returns a short-lived access token plus
  a rotated refresh token. Failed passwords return the same generic error as an
  unknown email so the endpoint does not reveal which accounts exist.
- New customers create an account with `POST /v1/auth/signup/request` followed
  by `POST /v1/auth/signup/verify` (email, 6-digit code, password). A legacy
  passwordless account sets its first password through the same flow; an
  account that already has a password returns `409`.
- Forgot-password uses `POST /v1/auth/password/reset/request` then
  `POST /v1/auth/password/reset/verify` (email, code, new password). Resetting
  or changing a password revokes every refresh token and returns a fresh
  session. Signed-in customers can set or replace their password with
  `POST /v1/me/password`, proving the current password when one exists.
- OTP challenges now carry a `purpose` (`login`, `signup`, `password_reset`,
  `email_change`), so a code issued for one flow cannot be replayed in another.
  Migration `0014_customer_auth_purposes` adds the column and the
  `ix_otp_email_purpose_created` index; the worker selects the matching email
  template by purpose.
- Email templates are purpose-specific: "Verify your Card Tracker email"
  (signup), "Reset your Card Tracker password", "Confirm your new Card Tracker
  email", and the legacy sign-in code template.
- The mobile app gates the whole platform behind authentication. Expo Router's
  `Stack.Protected` hides every shop, cart, hold, alert, request, and account
  route until the session is hydrated and signed in; an unauthenticated visit to
  a protected route redirects to `/login?next=...` and returns there after
  sign-in. The sign-in screen also offers create-account and forgot-password
  flows, keeps the English/Serbian toggle, and shows password-set status in
  Account.
- The legacy `/v1/auth/otp/request` and `/v1/auth/otp/verify` routes remain for
  older clients, but the mobile app no longer uses OTP for everyday sign-in.

### Email authenticity checks — 2026-11-13

- Every email entry point now normalizes the address and requires the domain to
  publish MX records: customer signup, password reset, email change, guest
  reservations, restock alerts, special orders, staff creation, and the demo
  seed. Addresses on known disposable/temporary providers are rejected.
- Login and OTP-verification payloads intentionally skip the DNS check so an
  existing account can still sign in during a resolver outage; OTP verification
  already proves control of the mailbox.
- The check is DNS-only. It does not connect to remote SMTP servers, which would
  be slow, unreliable, and an SSRF risk. A definitive "no MX" response is
  rejected; a transient resolver failure is logged and allowed so a DNS outage
  does not block all signups.
- `CARDTRACKER_EMAIL_DOMAIN_CHECK_ENABLED` (default `true`) is a kill switch and
  `CARDTRACKER_EMAIL_DOMAIN_CHECK_TIMEOUT_SECONDS` (default 3) bounds lookups.
  Reserved `example.com`/`.test`/`.invalid` domains are exempt only outside
  production so the demo seed and tests stay offline-friendly.
- Mobile already renders the API's 422 detail in the sign-in, create-account,
  reset, and email-change forms, so no client-side change was required.

---

## 3. Verification status

| Check | Result |
| --- | --- |
| Root Python suite (`pytest --cov --cov-branch`) | **351 passed, 100% line/branch** |
| Backend SQLite suite | **411 passed, 13 PostgreSQL tests skipped, 100% line/branch** |
| Backend with PostgreSQL test URLs | **424 passed, 100% line/branch** |
| Backend PostgreSQL-only suite (RLS, customer claiming, notifications, locking) | **13 passed** |
| Backend customer password tests | `tests/test_customer_passwords.py`: signup, login, reset, change, purpose isolation, rate limits, and session revocation |
| Backend email validation tests | `tests/test_email_validation.py`: normalization, MX checks, disposable providers, resolver outages, production/dev exemptions, caching, API 422s, and demo-seed rejection |
| Backend staff notification tests | `tests/test_staff_notifications.py`: inbox listing/pagination, unread counts, read/read-all, tenant isolation, inactive staff, and every event render/enqueue path |
| Backend account/session tests | `tests/test_customer_accounts.py`: **22 passed**, including per-device logout |
| Backend Ruff lint / changed-file formatting / mypy | Clean |
| Alembic `0008_customer_notifications` downgrade → upgrade | Verified on SQLite and PostgreSQL; notification customer RLS policy and push diagnostics recreated; `alembic_version` widened to 64 chars |
| Admin ESLint / TypeScript / production build | Clean |
| Admin Vitest logic/API-client coverage | **23 passed, 100% statements/branches/functions/lines** |
| Admin production source maps | **0** `.map` files in `dist/` |
| Admin Playwright suite | **9 passed** including owner notifications, unread badge, mark-all-read, card thumbnails, and the archive flows |
| Generated API snapshot/types | `admin/openapi.json` and admin/mobile `schema.d.ts` regenerated; archive delete/retention endpoints and fields present, no manual type edits |
| Mobile TypeScript / ESLint | Clean |
| Mobile Vitest `src/lib/**` coverage | **54 passed, 100% statements/branches/functions/lines** |
| Mobile `expo-doctor` | **20/20** |
| Mobile production web export | Passed |
| Mobile browser smoke test (local API) | **2 passed**: forced sign-in + locale toggle, and protected-route redirect |
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

Latest stock-archive validation (2026-11-08):

- Backend suite: **333 passed, 13 PostgreSQL-only skipped**, 100% statement and
  branch coverage. The new `tests/test_stock_archive.py` covers archive-all,
  tenant scoping, reserved-copy reporting, reservation completion after
  archiving, blocked new holds/edits and special-order conversion, manual
  restore, create/import restore, archived export, dashboard counts, repricing,
  and restock suppression.
- Backend Ruff check and formatting: clean.
- Alembic `0011_stock_archive` upgrade → downgrade to `0010` → upgrade verified
  on a temporary SQLite database; `archived_at` and
  `ix_stock_tenant_archived` appear and disappear with the revision.
- Admin ESLint, TypeScript, Vitest (**23 passed**, 100% logic coverage), and
  production build: clean. Playwright smoke suite: **9 passed**, including the
  archive confirmation and archived-view navigation.
- Mobile TypeScript and ESLint: clean; Vitest **49 passed**, 100%
  statements/branches/functions/lines.
- `admin/openapi.json` and both generated `schema.d.ts` files were regenerated
  from the running app; no manual API type edits.

Latest archive deletion/retention validation (2026-11-09):

- Backend suite: **347 passed, 13 PostgreSQL-only skipped**, 100% statement and
  branch coverage. `tests/test_stock_archive.py` additionally covers single and
  bulk deletion, active-hold skipping, tenant isolation, reservation-history
  preservation after stock removal, retention settings and validation, manual
  purge, lazy purge on the archived listing, and defensive handling of open
  reservations whose stock row disappeared.
- Backend Ruff check/formatting and mypy: clean.
- Alembic `0012_archive_retention` upgrade → downgrade to `0011` → upgrade
  verified on a temporary SQLite database; the retention column/check and
  nullable `SET NULL` stock foreign key appear and disappear with the revision.
  The local development database was migrated to `0012_archive_retention`.
- Admin ESLint, TypeScript, Vitest (**23 passed**), production build: clean.
  Playwright smoke suite: **9 passed**, including the archived delete-all
  confirmation and the retention field round-trip.
- Mobile TypeScript and ESLint: clean; Vitest **49 passed**, 100%
  statements/branches/functions/lines.
- `admin/openapi.json` and both generated `schema.d.ts` files were regenerated
  from the app; no manual API type edits.

Latest staff notification validation (2026-11-13):

- Backend suite: **384 passed, 13 PostgreSQL-only skipped**, 100% statement and
  branch coverage. The new `tests/test_staff_notifications.py` covers inbox
  listing and pagination, unread counts, mark-one/mark-all read, tenant and user
  isolation, inactive-staff filtering, every staff render kind, and the
  reservation/expiry/special-order enqueue paths.
- Backend with PostgreSQL test URLs: **397 passed**, 100% statement and branch
  coverage.
- Admin ESLint, TypeScript, Vitest (**23 passed**, 100% logic coverage), and
  production build: clean. Playwright smoke suite: **9 passed**, including the
  staff notification list, unread badge, mark-all-read, and all prior flows.
- Mobile TypeScript and ESLint: clean; Vitest **54 passed**, 100%
  statements/branches/functions/lines.
- Root Ruff lint/format and mypy: clean.
- `admin/openapi.json` and both generated `schema.d.ts` files were regenerated
  from the running app; the staff notification endpoints and schemas are
  present with no manual API type edits.

Latest customer password auth validation (2026-11-13):

- Backend SQLite suite: **397 passed, 13 PostgreSQL-only skipped**, 100%
  statement and branch coverage (4,232 statements, 1,036 branches). Backend
  with PostgreSQL test URLs: **410 passed**, 100% statement and branch coverage.
  The new `tests/test_customer_passwords.py` covers signup verification,
  password login, reset, change, per-purpose OTP isolation, rate limits, and
  refresh-token revocation after credential changes.
- Migration `0014_customer_auth_purposes` adds `customer_otp_challenges.purpose`
  (server default `login`) and `ix_otp_email_purpose_created`. Responses expose
  `CustomerOut.has_password`; no new password column was needed because
  `users.password_hash` already existed for staff accounts.
- `admin/openapi.json` and both generated `schema.d.ts` files were regenerated
  from the running app; the login/signup/reset/change endpoints and the
  `has_password` field are present with no manual API type edits.
- Alembic head is now `0014_customer_auth_purposes`.
- Mobile TypeScript, ESLint, and production web export: clean. Vitest:
  **54 passed, 100% statements/branches/functions/lines**. Playwright:
  **2 passed** (forced sign-in + locale toggle, and protected-route redirect).
- Backend Ruff lint/format and mypy on changed code: clean; two pre-existing
  mypy errors remain in `tests/test_scryfall_refresh.py` and `api/staff.py`.

Latest email authenticity validation (2026-11-13):

- Backend SQLite suite: **411 passed, 13 PostgreSQL-only skipped**, 100% line
  and branch coverage. Backend with PostgreSQL test URLs: **424 passed**, 100%.
- `tests/test_email_validation.py` adds 14 tests for normalization, disposable
  providers (including subdomains), MX success, NXDOMAIN/NoAnswer rejection,
  transient DNS failures, the development/production reserved-domain split, the
  disabled-check switch, caching, API 422 responses, and demo-seed rejection.
- Verified against real DNS: `gmail.com` and `outlook.com` accepted;
  `mailinator.com` and a nonexistent domain rejected.
- Ruff lint/format and mypy on the changed backend files: clean.
- No mobile code change was needed; the API client already displays the 422
  detail in the sign-in, create-account, reset, and email-change error text.

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

The password-signup, sign-in, and reset flows are working behind a mandatory
gate, including QR/deep-link entry, card detail, restock alerts, special orders,
`/v1/me`, guest-row claiming, and account profile update/deletion. The app also
includes push
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

5. Offline and sync reliability — **implemented 2026-11-08**
   - The app hydrates a persisted React Query snapshot on cold launch, so
     previously loaded shop, card, hold, alert, and account data can render
     without a live request.
   - Guest rows remain device-local. When a signed-in account exposes a row with
     the same id, the account copy wins for display while the guest copy stays
     intact in local storage and is never silently overwritten.
   - Sign-out, account switch, email change, deletion, and successful guest-row
     claiming cancel account-scoped queries and rewrite or remove the persisted
     snapshot. Guest data and the cart are deliberately kept.
   - Writes are not queued as offline edits; create/accept/cancel actions still
     require a live API request.
   - Focused Vitest coverage exists for snapshot persistence, malformed-payload
     handling, serialized writes, account-cache clearing, and guest/account
     merge rules.

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

2. **Finish offline/cache safety — implemented 2026-11-08**
   - 2.1 Mobile documents cached-read behavior and that writes are not queued
     offline.
   - 2.2 Guest data stays device-local; account rows win id conflicts without
     deleting or overwriting the guest copy.
   - 2.3 Account-scoped caches are cleared and the persisted snapshot rewritten
     on sign-out, account switch, email change, deletion, and guest-row claiming.
   - 2.4 Vitest covers snapshot persistence, malformed payloads, serialized
     writes, account-cache clearing, and guest/account merge rules.
   - **Done when:** stale account data cannot appear after identity changes,
     and offline edits have a predictable outcome. **Met:** cached reads are
     available, and writes are never presented as saved without a live API
     response.

3. **Prepare production app links and delivery**
   - 3.1 Choose and configure the public HTTPS app domain and hosting for the
     mobile web page and platform association files.
   - 3.2 Deploy the admin with `admin/public/_headers` (or equivalent CSP and
     security headers) enabled.
   - 3.3 Verify QR links and app links on a real Android and iOS device both
     with the app installed and from a fresh browser; record the tested URLs
     and results.
   - 3.4 Configure production SMTP and push-provider credentials; send and
     verify OTP email and push notifications, including opt-out behavior.
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
   - Monitor staff notification volume and add per-event preferences if the
     pilot inbox becomes noisy; customer in-app and push notifications remain
     the primary delivery channels.
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
  coverage are implemented. Cached reads work offline, but writes are not
  queued as offline edits and still require a live API request. The signed-in
  native multi-device smoke remains before pilot.
- Printed QR codes can use the canonical HTTPS public app URL and still fall
  back to the `cardtracker://` custom scheme, but production domain
  configuration and app-store install paths still need final deploy-time setup.
- Notification delivery is gated by customer preferences at the worker level,
  so push (and the idle email path) respect opt-out, quiet hours, and
  per-channel toggles; in-app feed rows always appear for signed-in customers.
  The customer delivery log is per-channel: one business event can appear as a
  separate in-app and push entry. It returns rendered titles but deliberately
  omits message bodies so unsubscribe tokens do not leak.
- Push-device diagnostics show the last sanitized error and failure count on the
  token, and invalid provider tokens are revoked automatically. A customer can
  re-enable delivery by registering the device again.
- Restock alerts are one-shot and in-app/push-based for signed-in customers.
  Guest alerts stay pending and are claimed once the same email signs in, so
  the first restock after signing in fires them. Alert links prefer the
  canonical public app URL while remaining compatible with the custom-scheme
  fallback.
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
