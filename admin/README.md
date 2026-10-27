# Card Tracker — Shop admin

Responsive web admin for shop owners and staff. It is a thin client over the
platform API: all stock, reservation, and tenant rules live in `backend/`.

Built with Vite, React, TypeScript, and TanStack Query. No UI framework, no
server-side rendering — that keeps one backend as the only source of truth.

## Screens

| Route | Purpose |
| --- | --- |
| `/login` | Shop address + email + password (staff JWT) |
| `/` | Dashboard: pending requests, active holds, sold today, low/stale stock |
| `/stock` | Search, on-hand/price/visibility edits, adjustments, in-store sales |
| `/reservations` | Queue by status, accept/ready/cancel, complete with per-line quantities |
| `/requests` | Special orders: quote, decline, and convert an accepted request into a reservation |
| `/team` | Owner-only: add staff, change roles, deactivate accounts |
| `/activity` | Owner-only: audit trail with action filters |
| `/settings` | Branding, hold duration, payment instructions, contact, directory opt-in |

Stock numbers always pair colour with a text label (available / reserved / out)
so they remain readable without colour vision. A "N waiting" badge on a stock
row shows how many customers asked for a restock alert on that exact variant.

Owner-only actions: saving settings uses `PATCH /v1/staff/settings`, which the
API restricts to the `owner` role. Staff get a clear message instead of a crash.

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

```bash
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
npm run build        # typecheck + production bundle
npm run test:e2e     # Playwright, starts its own API and dev server
```

The Playwright suite starts a throwaway API (`e2e/api-server.sh`) with a seeded
SQLite database and runs the real UI against it:

- wrong password is rejected, then sign-in succeeds;
- adjusting stock is visible to the public storefront API;
- a reservation can be confirmed, marked ready, and completed, and stock is
  released exactly once;
- settings save and survive a reload;
- a special order can be quoted, accepted by the customer, and converted into a
  confirmed reservation (stock availability drops by one);
- restock-alert demand appears as a "waiting" badge on the stock row.

It uses `CARDTRACKER_E2E_PYTHON` if set, otherwise `../.venv/bin/python`.

## API types

`openapi.json` is a snapshot of the backend contract and
`src/api/schema.d.ts` is generated from it, so request and response types cannot
drift by hand.

```bash
# with the API running on :8000
npm run api:dump     # refresh openapi.json
npm run api:types    # regenerate src/api/schema.d.ts
```

`src/api/types.ts` gives those generated shapes short names.

## Known gaps

- Excel (`.xlsx`) stock import; CSV only for now.
- Roles beyond owner/staff.
- Push delivery (email only; the API outbox worker supports console and SMTP).
- Customer-facing restock/special-order screens (the mobile app is next).
- Opening-hours editor: the API stores them, the form does not edit them yet.
- Reports and per-shop subscription billing.
- The API rate limiter is in-process, so it assumes a single worker for now.
