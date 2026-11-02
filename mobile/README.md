# Card Tracker — Customer App

Expo + React Native + TypeScript customer app for the multi-vendor platform.
The Step 5 slice covers shop discovery, storefront browsing, card detail,
QR/deep-link entry, local cart, guest reservation, restock alerts,
special-order requests, confirmation, history, cancellation, optional
email-OTP customer accounts with `/v1/me` data, and native push notifications.

The API is the source of truth. Guest checkout works without an account; the
app keeps a local cart and the guest tokens/metadata needed to reopen a hold,
manage a restock alert, or track a special order. An account session is held
in memory only and combines `/v1/me` rows with device-local guest rows.

## What works

- Shop directory with search and pull-to-refresh.
- Shop storefront with live stock, search, sort, availability filter, and
  cursor-based “load more” pagination.
- Local cart persisted on the device, per shop.
- Guest reservation form with name/email/phone/note validation.
- Reservation confirmation with reference, countdown, line items, total, and
  payment instructions.
- Hold history on the home screen, combining account and device-local rows.
- Reservation detail refreshes from the API using the account or guest token.
- Cancel a hold from the app; stock is released immediately.
- Sold-out card detail shows a single-opt-in restock form. Alerts are listed on
  a dedicated screen, can be removed from the app, and are unsubscribed with a
  signed, stateless token.
- Special-order request form with card details, quantity, optional target
  price, and contact validation; local request list and detail screen.
- Special-order detail refreshes from the API with an account or guest token.
  Customers can accept or cancel a quote, and see when the shop converts it
  into a hold.
- Optional native push notifications for signed-in customers. The account
  screen asks for permission in context, registers the raw FCM/APNs device
  token with the API, refreshes rolled tokens, unregisters on sign-out, and
  opens the relevant shop or card when a notification is tapped. The app never
  uses the Expo Push Service.
- Optional email OTP account. Signing in claims unowned guest reservations,
  restock alerts, and special orders with the same verified email, then shows
  account data across shops and devices. Signed-in create forms use the
  account email and still work with the existing guest response.
- Guest tokens are stored with Expo SecureStore on native platforms. The
  customer account token is intentionally memory-only: a cold launch starts
  signed out, while backgrounding and reopening the same process keeps the
  session until the server expiry.
- In-store QR scanning with `expo-camera`: a shop code opens the storefront and a
  card code opens that card. Manual shop-code entry is always available, which
  is also how the web preview works.
- Dedicated card-detail route with a large image, price, live availability,
  variant details, and add-to-hold controls.
- Deep links `cardtracker://shop/<slug>` and
  `cardtracker://shop/<slug>/card/<stock-id>` open the same routes on cold start
  or while the app is running.

Not in this slice yet: offline cache, localization, device E2E, and account
profile editing, email change, deletion, or refresh/revocation.

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

For account sign-in, also run the notification worker (the OTP email is queued
through the existing outbox). In development, enable the debug code so the app
can display it without SMTP:

```bash
cd backend
CARDTRACKER_OTP_DEBUG_CODE=true ../.venv/bin/python -m app.workers.notifications
```

The default `console` notification backend logs only the subject, never the OTP
or recipient. Use `CARDTRACKER_OTP_DEBUG_CODE=true` only in development/test;
the API never returns the code in production.

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
2. Tap a card to open its detail page, then tap **Add to hold**.
3. Tap **Review your hold**.
4. Fill in a name and email and tap **Request this hold**.
5. The confirmation screen shows the public reference and expiry.
6. Tap **Cancel this hold** to release the stock.

### Restock alerts and special orders

1. Open a sold-out card at a shop and fill in **Notify me**. The app keeps the
   alert metadata locally and the signed manage token in SecureStore.
2. Open **Restock alerts** from the home screen to review or remove an alert.
3. On any card, choose **Need a different copy?** to open the special-order
   form. The request is tracked locally with its guest token.
4. Open **Special orders** from the home screen to track status, accept a quote,
   or cancel the request. Accepting does not take payment; the shop converts
   the request into a normal hold at the shelf price.

### Optional account

1. Tap the account bar on the home screen and enter your email.
2. Tap **Email me a sign-in code**. With the development settings above, the
   code response is shown in the app; in production it arrives by email.
3. Enter the six-digit code. The backend creates a global customer account on
   first use and claims unowned guest rows with the same email.
4. While signed in, the home screen, alerts, and special orders show account
   data for all shops, plus any remaining device-local guest rows. Detail
   screens use account actions where possible and fall back to guest tokens.
5. **Sign out** clears the in-memory session and account query cache. Local
   guest data stays on the device. Closing and reopening the app also starts
   signed out because the account token is never persisted.

Guest checkout remains available at every step. Signed-in create forms lock the
email to the account address and still return the normal guest token for local
detail access.

### Push notifications

Push needs a native build on a physical device; Expo Go, simulators, and the web
preview cannot obtain a real FCM/APNs token. Tap **Enable push notifications**
on the signed-in account screen to prompt for permission and register the
device. Tapping a notification opens the shop or card carried in its `url` data
field, including when the app was cold-started by the notification.

Android production builds need a Firebase project and `google-services.json`
wired into the EAS build (`android.googleServicesFile`). iOS builds need an APNs
key and the Push Notifications capability in the EAS credentials. On the API,
set `CARDTRACKER_PUSH_BACKEND=native` and the matching FCM/APNs variables from
[`backend/.env.example`](../backend/.env.example). The API talks directly to
FCM HTTP v1 and APNs HTTP/2; it does not use the Expo Push Service.

To try the QR entry without a printed code, open `/scan` from the home screen
and type `bolt-shop` into **Enter a code by hand**. The admin prints the matching
shop QR code from **Settings → Shop QR code**.

### Deep links

The app scheme is `cardtracker://`. Supported links:

| Link | Opens |
| --- | --- |
| `cardtracker://shop/<slug>` | Storefront |
| `cardtracker://shop/<slug>/card/<stock-id>` | Card detail |

The scanner also accepts the equivalent `https://…/shop/…` path, Expo Go
`exp://…/--/shop/…` links, a bare `/shop/…` path, and a shop slug typed by hand.
Unknown schemes and paths are rejected instead of opening an arbitrary route.

```bash
# Android
adb shell am start -a android.intent.action.VIEW -d "cardtracker://shop/bolt-shop"

# iOS simulator
xcrun simctl openurl booted "cardtracker://shop/bolt-shop"
```

## Commands

```bash
npm run typecheck     # tsc --noEmit
npm run lint          # expo lint
npm audit --audit-level=high  # dependency advisories
npm run test:coverage # Vitest + 100% line/branch/function gate
npm run web           # browser preview
npm run api:types     # regenerate src/api/schema.d.ts from ../admin/openapi.json
npm run doctor        # expo-doctor
```

`package.json` pins two security overrides: `zod@4.6.7` and the maintained
`@stackline/deepmerge` drop-in replacement. Both replace vulnerable transitive
Expo dependencies while keeping the public package names and APIs used by the
Expo CLI.

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
    index.tsx                  shop directory + combined holds/requests
    account.tsx                email OTP sign-in / signed-in account
    scan.tsx                   QR scanner + manual code entry
    shop/[slug]/index.tsx      storefront
    shop/[slug]/card/[stockId].tsx  card detail
    shop/[slug]/cart.tsx       cart + guest/signed-in reservation form
    reservation/[id].tsx       confirmation / detail / cancel
    alerts.tsx                 combined restock alerts + unsubscribe
    requests/index.tsx         combined special orders
    requests/new.tsx           special-order request form
    requests/[id].tsx          quote detail / accept / cancel
  api/                         generated schema, client, query hooks
  components/                  reusable UI
  lib/                         config, deeplink parser, formatting, account merge, timers
  state/                       auth (memory-only), push, cart, reservations, alerts, requests
  theme.ts                     colours, spacing, type scale
```

## Verification

Current local verification:

- `npm run typecheck` — clean
- `npm run lint` — clean
- `npm run test:coverage` — **31 tests, 100% statements/branches/functions/lines**
  for `src/lib/**` (excluding the `useNow` timer hook)
- `npm run export:web` — production web bundle builds
- `npm run doctor` — 20/20 checks
- Browser smoke test against the local API: scan entry by hand → storefront →
  card detail → add to hold; direct card deep link; card → shop link
- The deep-link parser was checked against custom-scheme, `https`, Expo Go,
  path-only, bare-slug, malformed UUID, traversal, and foreign-scheme inputs
- Account/OTP/claim behavior is covered by the backend SQLite and PostgreSQL
  suites; a signed-in browser/device smoke is still a release check

The Vitest set covers the pure logic modules: config/API-host resolution,
deep-link parsing and link generation, money/date/time formatting,
account/guest row merging, guest-token storage, push target parsing, and
idempotency keys. Camera
scanning itself needs a device camera; use Expo Go or a development build. The
web preview has no camera in headless checks, so the same browser test
exercises the manual-entry fallback. Device E2E is still not wired up.

## Security notes

- The customer account token is a 12-hour bearer credential held only in
  memory. It is never written to SecureStore or AsyncStorage, so a cold launch
  requires a new OTP. Do not add persistence without redesigning sign-out and
  cache clearing.
- The guest reservation token is a credential. Native builds store it in
  SecureStore; the web preview falls back to AsyncStorage because SecureStore
  has no web implementation. Do not treat the web preview as a production
  customer channel.
- The development OTP debug code is returned by the API only when
  `environment` is `development`/`test` and `CARDTRACKER_OTP_DEBUG_CODE=true`.
  Never enable it on a production API.
- The app sends an `Idempotency-Key` on reservation creation and reuses it
  while a submission is retried, preventing duplicate holds after a lost
  response.
- The app never sends or logs payment details; payment remains in store.
- The QR parser accepts only Card Tracker shop/card links (custom scheme, the
  same https path, Expo Go links, paths, or a bare slug). Other schemes and
  unknown paths are rejected, so a scanned foreign QR code cannot navigate the
  app somewhere arbitrary.
- Camera permission is requested only when the customer opens the scanner, and
  the camera view unmounts when the screen loses focus.
