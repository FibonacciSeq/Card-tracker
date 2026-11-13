# Card Tracker — Shop admin

Responsive web admin for shop owners and staff. It is a thin client over the
platform API: all stock, reservation, and tenant rules live in `backend/`.

Built with Vite, React, TypeScript, and TanStack Query. No UI framework, no
server-side rendering — that keeps one backend as the only source of truth.

The customer-facing Expo app lives in [`../mobile`](../mobile); this admin is
staff-only.

## Screens

| Route | Purpose |
| --- | --- |
| `/login` | Shop address + email + password (staff JWT) |
| `/` | Dashboard: pending requests, active holds, sold today, low/stale stock |
| `/stock` | Search, on-hand/price/visibility edits, adjustments, in-store sales, CSV import/export, archive-all, archived-view restore/delete, retention-aware archived view |
| `/reservations` | Queue by status, accept/ready/cancel, complete with per-line quantities |
| `/requests` | Special orders: quote, decline, and convert an accepted request into a reservation |
| `/team` | Owner-only: add staff, change roles, deactivate accounts |
| `/activity` | Owner-only: audit trail with action filters |
| `/settings` | Branding, hold duration, payment instructions, contact, directory opt-in, printable shop QR code |

Stock numbers always pair colour with a text label (available / reserved / out)
so they remain readable without colour vision. A "N waiting" badge on a stock
row shows how many customers asked for a restock alert on that exact variant.

The stock page has **Active stock** and **Archived** tabs. **Archive all stock**
moves every active row for the current shop into the archived tab after a
confirmation step. Archived rows are hidden from the customer app and from new
holds, keep existing reservation history, and can be restored one row at a time.
Importing or creating the same card and variant again restores the matching
archived row automatically. The archived tab has its own CSV export
(`?archived=true`); the normal export excludes archived rows. It also offers
per-row **Delete** and **Delete all archived** actions with confirmation.
Permanent deletion keeps rows that still have active customer holds. Settings has
an **Archived stock** retention field (0 = keep forever) for automatic cleanup;
the expiry worker and the archived view both enforce it.

Stock CSV import accepts both the app's exported stock template and ManaBox
collection exports. ManaBox purchase prices are converted from their source
currency using the latest published daily reference rate, then shop-wide rules
set the selling price: costs below a threshold use a fixed amount, while costs
at or above it receive a percentage markup and round strictly upward to the
next amount ending in 0. Workers can edit and save these rules in the import
panel. The app's own exported stock prices remain unchanged by these rules.
The daily exchange rate is provided by
[Exchange Rate API](https://www.exchangerate-api.com). Use **Check file** to
preview catalog issues and see the rate used before changing stock.

Owner-only actions: saving settings uses `PATCH /v1/staff/settings`, which the
API restricts to the `owner` role. Staff get a clear message instead of a crash.

Settings also renders the shop QR code for the canonical public app URL
`https://app.cardtracker.local/shop/<slug>` (with a `cardtracker://shop/<slug>`
app fallback shown underneath), entirely in the browser with copy and
download-PNG actions. The customer app scans that code from its home screen,
and the public HTTPS URL keeps a browser-only customer flow working even before
an in-app install.

The reservation queue only offers transitions the API accepts:
`REQUESTED → CONFIRMED → READY → COMPLETED`, with cancellation from any active
state. It does not offer the invalid `REQUESTED → READY` jump. The dashboard,
reservation list, and reservation detail poll every 20 seconds so new guest
holds appear without a manual refresh.

## Security and error handling

- Production builds set `sourcemap: false`; `npm run build` must leave no
  `.map` files in `dist/`.
- `public/_headers` ships a CSP and browser security headers for static hosts.
  Vite also applies dev/preview headers; the production host must serve the
  `_headers` file itself. If `VITE_API_BASE_URL` points at another origin, add
  that origin to `connect-src` in `public/_headers`.
- Client logging is development-only and sanitized. `src/lib/logger.ts` records
  only error type/status, never `ApiError.payload`, request bodies, tokens, or
  customer details. ESLint enforces `no-console` everywhere except that file.
- `ErrorBoundary` replaces a crashed screen with a reload fallback and global
  `error`/`unhandledrejection` handlers report sanitized metadata.

## Local development

Requires Node 22 and the backend running on port 8000.

```bash
cd admin
npm install
npm run dev          # http://127.0.0.1:5173
```

Vite proxies `/v1` to `http://127.0.0.1:8000`, so there is no CORS setup and no
API URL to configure. Override the proxy target with `CARDTRACKER_API_URL`, or
point the built app at another host with `VITE_API_BASE_URL`.

Seed a shop to sign in with:

```bash
cd backend
CARDTRACKER_AUTO_CREATE_TABLES=true ../.venv/bin/python -m app.cli.seed_demo \
  --slug bolt-shop --name "Bolt Shop" \
  --email owner@example.com --password secret-password
```

## Checks

Requires Node 22 and npm. Install once with `npm ci` (or `npm install` for a
local development tree).

```bash
npm run lint          # eslint, including no-console
npm run typecheck     # tsc --noEmit
npm run test:coverage # Vitest + 100% line/branch/function gate
npm run build         # typecheck + production bundle
find dist -name '*.map'   # must print nothing
npm run test:e2e      # Playwright, starts its own API and dev server
```

The Vitest gate currently covers **23 tests** across `src/api/client.ts`,
`src/auth/session.ts`, and `src/lib/**` at **100% statements, branches,
functions, and lines**. UI screens are intentionally outside the line-coverage
set; the Playwright suite exercises them end to end.

The Playwright suite starts a throwaway API (`e2e/api-server.sh`) with a seeded
SQLite database and runs the real UI against it (8 tests). It uses ports 8011
and 5174 by default so an API or Vite development server on the usual ports
does not block the tests. Override these with `CARDTRACKER_E2E_API_PORT` and
`CARDTRACKER_E2E_ADMIN_PORT` if needed:

- wrong password is rejected, then sign-in succeeds;
- adjusting stock is visible to the public storefront API;
- a reservation can be confirmed, marked ready, and completed, and stock is
  released exactly once;
- settings save and survive a reload, and the shop QR code and its deep link
  are rendered;
- a special order can be quoted, accepted by the customer, and converted into a
  confirmed reservation (stock availability drops by one);
- restock-alert demand appears as a "waiting" badge on the stock row.

It uses `CARDTRACKER_E2E_PYTHON` if set, otherwise `../.venv/bin/python`.

## API types

`openapi.json` is a snapshot of the backend contract and
`../shared/api/schema.d.ts` is generated from it, so request and response types
cannot drift by hand.

```bash
# with the API running on :8000
npm run api:dump     # refresh openapi.json
npm run api:types    # regenerate ../shared/api/schema.d.ts
```

`src/api/types.ts` gives those generated shapes short names.

## Known gaps

- Excel (`.xlsx`) stock import; CSV only for now.
- Roles beyond owner/staff.
- Push delivery (email only; the API outbox worker supports console, SMTP, and
  a pending-only `none` mode).
- Push notifications are not implemented; restock and special-order updates
  are email-based. The mobile app supports optional memory-only customer
  accounts and keeps guest metadata locally for signed-out use.
- Opening-hours editor: the API stores them, the form does not edit them yet.
- Reports and per-shop subscription billing.
- No production client telemetry/error reporting endpoint; the logger is
  development-only and intentionally omits payloads.
- The queue/dashboard use 20-second polling rather than server-sent events or
  websockets.
- The production static host must serve `public/_headers` (or equivalent CSP and
  security headers); Vite only applies them in dev/preview.
- The API rate limiter is in-process, so it assumes a single worker for now.
