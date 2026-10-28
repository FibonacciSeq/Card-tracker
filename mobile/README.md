# Card Tracker — Customer App

Expo + React Native + TypeScript customer app for the multi-vendor platform.
This is the Step 5 guest vertical slice: shop discovery, storefront browsing,
local cart, guest reservation, confirmation, hold history, and cancellation.

The API is the source of truth; the app only keeps a local cart and the guest
reservation tokens needed to reopen a hold.

## What works

- Shop directory with search and pull-to-refresh.
- Shop storefront with live stock, search, sort, availability filter, and
  cursor-based “load more” pagination.
- Local cart persisted on the device, per shop.
- Guest reservation form with name/email/phone/note validation.
- Reservation confirmation with reference, countdown, line items, total, and
  payment instructions.
- Hold history on the home screen.
- Reservation detail refreshes from the API using the guest token.
- Cancel a hold from the app; stock is released immediately.
- Guest tokens are stored with Expo SecureStore on native platforms.
- Deep-link scheme `cardtracker://` is configured for future QR/deep links.

Not in this slice yet: restock alerts UI, special-order UI, customer accounts,
push notifications, offline cache, QR scanning, and device E2E.

## Run it

Start the API from the repository root:

```bash
cd backend
CARDTRACKER_AUTO_CREATE_TABLES=true ../.venv/bin/uvicorn app.main:app \
  --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is required when running on a phone; the phone cannot reach
the API if Uvicorn only binds to `127.0.0.1`.

If the local database is empty, seed the demo shop in another terminal:

```bash
cd backend
../.venv/bin/python -m app.cli.seed_demo \
  --slug bolt-shop \
  --name "Bolt Shop" \
  --email owner@example.com \
  --password secret-password
```

The local development database currently contains `bolt-shop` with three
stock rows. It is git-ignored.

Start the app:

```bash
cd mobile
npm install
npm start
```

Then press `i` for the iOS simulator, `a` for an Android emulator, or scan the
QR code with Expo Go. Use `npm run web` for a browser preview.

### API address

In development the app derives the API host from the Expo dev-server address
and assumes port `8000`. That works for Expo Go on the same LAN and for
simulators.

Override it when the API is elsewhere:

```bash
# .env.local (ignored by git)
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.20:8000
```

Restart with `npx expo start --clear` after changing the environment file.
For production builds set `EXPO_PUBLIC_API_BASE_URL` to the public HTTPS API.

### Demo flow

1. Open the app and tap **Bolt Shop**.
2. Add a card, then tap **Review your hold**.
3. Fill in a name and email and tap **Request this hold**.
4. The confirmation screen shows the public reference and expiry.
5. Tap **Cancel this hold** to release the stock.

## Commands

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # expo lint
npm run web         # browser preview
npm run api:types   # regenerate src/api/schema.d.ts from ../admin/openapi.json
npm run doctor      # expo-doctor
```

The API types are generated from the same committed OpenAPI snapshot as the
admin. Regenerate the snapshot in `admin/` first if the backend contract
changed:

```bash
cd admin
npm run api:dump
npm run api:types
cd ../mobile
npm run api:types
```

## Structure

```text
src/
  app/                         Expo Router routes
    index.tsx                  shop directory + local holds
    shop/[slug]/index.tsx      storefront
    shop/[slug]/cart.tsx       cart + guest reservation form
    reservation/[id].tsx       confirmation / detail / cancel
  api/                         generated schema, client, query hooks
  components/                  reusable UI
  lib/                         config, formatting, idempotency, timers
  state/                       cart and saved-reservation providers
  theme.ts                     colours, spacing, type scale
```

## Verification

Current local verification:

- `npm run typecheck` — clean
- `npm run lint` — clean
- `npm run export:web` — production web bundle builds
- `npm run doctor` — 20/20 checks
- Browser smoke test against the local API: shop directory → storefront →
  add card → guest hold → confirmation → cancel

Device E2E and unit tests are not wired up yet.

## Security notes

- The guest reservation token is a credential. Native builds store it in
  SecureStore; the web preview falls back to AsyncStorage because SecureStore
  has no web implementation. Do not treat the web preview as a production
  customer channel.
- The app sends an `Idempotency-Key` on reservation creation and reuses it
  while a submission is retried, preventing duplicate holds after a lost
  response.
- The app never sends or logs payment details; payment remains in store.
