# Customer accounts and guest-data claiming

Status: **implemented** on 2026-10-29.

This records the Step 5 account slice: optional customer accounts, email OTP
login, `/v1/me`, and automatic claiming of guest reservations, restock alerts,
and special orders. Guest checkout remains the default path.

## 1. Goals

- Let a customer sign in with an email OTP from the mobile app.
- Let the same account see its data across devices.
- Claim guest rows created before sign-in, and rows created on another device.
- Preserve guest checkout and every existing guest-token flow.
- Keep guest data device-local until the customer signs in.
- Keep the feature optional: browsing, guest holds, restock alerts, and special
  orders must continue to work without an account.

## 2. Decisions

| Decision | Choice |
| --- | --- |
| Identity model | One global customer account per normalized email, across all shops |
| Guest claiming | Automatic on every successful OTP verification, matched by verified email |
| Account creation | Created lazily on first successful OTP verification |
| OTP delivery | Existing notification worker drains OTP challenges; no synchronous SMTP call |
| OTP storage | No plaintext code at rest; code is derived from the challenge id and server secret |
| Session token | HS256 JWT, 12 hours, memory-only in the app |
| Mobile account data | Fetched from `/v1/me` and held in React Query; not merged into guest AsyncStorage |
| Sign-out | Remove account token and account query cache; leave device-local guest rows alone |
| App launch | No persisted account token, so a cold launch always starts signed out |

### Why global identity

A customer can hold cards at more than one shop. Per-shop accounts would force
duplicate accounts and make `/v1/me` ambiguous. The existing `User` row already
supports `role='customer'` and a nullable `tenant_id`; a global customer is a
`User` with `tenant_id = NULL`, which keeps the existing `customer_id` foreign
keys working without a destructive FK migration.

### Why automatic claiming

The customer has just proved control of the email with an OTP. Cross-device
recovery is impossible if claiming requires a token that only exists on the old
device. Matching on the verified email is therefore the primary rule. Rows
already linked to another customer are never reassigned.

## 3. Data model and migration

### 3.1 Global customer rows in `users`

A customer account is:

- `tenant_id = NULL`
- `role = "customer"`
- lower-cased `email`
- `is_active = true`
- `email_verified_at` set on first successful verification
- no password hash

Add a partial unique index:

```sql
CREATE UNIQUE INDEX uq_users_customer_global_email
ON users (lower(email))
WHERE role = 'customer' AND tenant_id IS NULL;
```

This is needed because the existing `(tenant_id, email)` unique constraint does
not prevent duplicate `NULL` tenant rows in SQLite or Postgres.

Add indexes for account reads:

- `(customer_id, created_at)` on `reservations`
- `(customer_id, created_at)` on `card_requests`
- `(customer_id, created_at)` on `restock_alerts`

### 3.2 OTP challenges

New global table `customer_otp_challenges`:

| Column | Purpose |
| --- | --- |
| `id` | UUID; also the OTP derivation input |
| `email` | Normalized recipient email, indexed |
| `expires_at` | 10 minutes after creation |
| `attempts` | Failed verification attempts |
| `consumed_at` | Set on success, replacement, or attempt exhaustion |
| `email_sent_at` | Set by the worker after successful delivery |
| `email_attempts` | Delivery retry count |
| `next_email_attempt_at` | Delivery backoff |
| `email_error` | Exception type / SMTP code only, never recipient or body |
| `created_at` | Request time |

Indexes:

- `(email, created_at)` for lookup and resend checks
- `(email_sent_at, next_email_attempt_at)` for the worker
- `(expires_at)` for cleanup

The table contains no OTP plaintext. The challenge row is also the email job;
there is no second outbox table.

### 3.3 Migration

New Alembic revision `0004_customer_accounts`:

1. Create `customer_otp_challenges` and indexes.
2. Create the partial unique customer-email index.
3. Create the three customer-id indexes.
4. On Postgres only, add permissive policies alongside the existing
   tenant-isolation policies:
   - `users_global_customer` allows global customer rows (`tenant_id IS NULL`
     and `role = 'customer'`);
   - `reservations_customer_own`, `card_requests_customer_own`, and
     `restock_alerts_customer_own` allow rows matching
     `current_setting('app.customer_id', true)`:

```sql
USING (
  customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
)
WITH CHECK (same expression)
```

Postgres combines permissive policies with `OR`, so tenant context still sees
all of a tenant's rows and customer context sees only that customer's rows.
`reservation_lines` stays tenant-only. Account reservation detail resolves the
reservation first with the customer context, then sets the tenant context before
loading lines. No row is returned without the customer_id filter.

Downgrade drops the OTP table/indexes and the added customer policies; the
original tenant-only policies and all existing rows remain untouched.

## 4. OTP lifecycle

### 4.1 Request

`POST /v1/auth/otp/request`

- Normalize the email: trim and lower-case.
- Apply two in-process rate limits:
  - per client IP;
  - per hashed email.
- Enforce a 60-second resend cooldown per email, also checked against the
  latest DB challenge so multiple API workers cannot bypass it.
- Mark any older unconsumed challenge as consumed and suppress its unsent email.
- Create a challenge with a 10-minute expiry.
- Return `202` immediately. The worker sends the email.
- The response never says whether an account already exists.

Suggested settings:

```text
otp_expiry_seconds = 600
otp_resend_seconds = 60
otp_max_attempts = 5
otp_request_ip_limit = 10 / 3600s
otp_request_email_limit = 5 / 900s
otp_verify_ip_limit = 20 / 900s
otp_verify_email_limit = 10 / 900s
otp_email_max_attempts = 5
customer_access_token_minutes = 720
otp_debug_code = false
otp_secret = ""  # falls back to jwt_secret
```

### 4.2 Code derivation

The code is 6 digits derived with HMAC-SHA256:

```text
code = HMAC(otp_secret, f"otp:{challenge_id}:{email}") mod 1_000_000
```

No plaintext code is stored in the DB or written to logs. The worker derives the
same code when rendering the email, and verification derives it again.

### 4.3 Delivery

The existing notification worker process gets one extra global pass:

- select unconsumed, unexpired challenges with no `email_sent_at`;
- respect `next_email_attempt_at`;
- render and send through the existing `console` / `smtp` sender;
- on success set `email_sent_at`;
- on failure store only the exception type / SMTP code, increment
  `email_attempts`, and back off.

Using the challenge row as the outbox means no separate auth email table and no
plaintext code in an outbox payload.

Development: `CARDTRACKER_OTP_DEBUG_CODE=true` returns `debug_code` in the
request response only when `environment` is `development` or `test`. Production
never returns it. `CARDTRACKER_NOTIFICATION_BACKEND=none` leaves challenges
unsent, same as the existing outbox behavior.

### 4.4 Verify

`POST /v1/auth/otp/verify`

- Apply IP and email rate limits.
- Load the newest unconsumed challenge for the email.
- Reject expired, missing, or exhausted challenges with a generic `401`.
- Compare with `hmac.compare_digest`; increment `attempts` on failure and
  consume the challenge after the limit.
- On success:
  1. consume the challenge;
  2. find or create the global customer account;
  3. set `email_verified_at`;
  4. claim matching guest rows;
  5. commit;
  6. issue a customer JWT.

Account creation race: the partial unique index is authoritative. If two
verifications race, the loser re-reads the existing account. The challenge
state and claim updates stay in one transaction.

Inactive accounts are rejected after a valid code with a generic forbidden
response.

## 5. Customer session token

Add:

```text
create_customer_access_token(customer_id)
decode_access_token(token)  # already exists
```

Payload:

```json
{
  "sub": "<customer user id>",
  "role": "customer",
  "scope": "customer",
  "iat": "...",
  "exp": "...",
  "iss": "cardtracker-platform"
}
```

No `tenant_id`: the account is global. `get_current_customer` checks:

- signature, issuer, expiry;
- `scope == "customer"`;
- `role == "customer"`;
- `tenant_id IS NULL`;
- `is_active`.

Staff endpoints keep their existing tenant JWT and cannot accept a customer
token. Customer endpoints cannot accept a staff token.

Token lifetime is 12 hours in this slice. The mobile app keeps it only in
memory, so a cold launch starts signed out and requires a new code. There is no
refresh token and no server-side revocation; backgrounding and reopening the
same app process keeps the in-memory session until the server expiry. Disabling
an account takes effect on the next request because `is_active` is checked. A
session/revocation table and refresh rotation are later work.

## 6. Guest claiming

On every successful verification, for each tenant:

```sql
UPDATE reservations
SET customer_id = :customer_id
WHERE tenant_id = :tenant_id
  AND customer_id IS NULL
  AND lower(email) = :email;

-- same for card_requests and restock_alerts
```

Rules:

- Only `customer_id IS NULL` rows are claimed.
- Rows already linked to another account are never reassigned.
- Matching is case-insensitive on email.
- Claiming is idempotent; the counts returned are the rows actually updated.
- All statuses are claimed, including historical completed/cancelled rows.
- Rows created by staff holds or special-order conversion are claimable too.
- The guest access token hash is left untouched, so existing guest-token
  flows still work after claiming.
- Claiming iterates tenants because RLS prevents a global email scan. Shop
  counts are small today; this can be replaced with a customer/tenant
  membership index later.

When a customer creates a row while signed in:

- the server attaches `customer_id`;
- the server uses the account email, not the submitted email;
- the response still includes the guest access token for backward
  compatibility and local offline detail;
- the mobile app saves the guest row as before and also refreshes `/v1/me`.

When a special order is converted to a reservation, pass the request's
`customer_id` into `create_staff_hold` so the new reservation is linked
immediately if the request already has an owner.

## 7. API contracts

All account endpoints require `Authorization: Bearer <customer token>` and
return `Cache-Control: no-store`.

### Auth

```http
POST /v1/auth/otp/request
{ "email": "you@example.com" }

202 {
  "expires_in": 600,
  "resend_after": 60,
  "debug_code": null
}
```

```http
POST /v1/auth/otp/verify
{ "email": "you@example.com", "code": "123456" }

200 {
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 43200,
  "is_new_account": true,
  "customer": {
    "id": "...",
    "email": "you@example.com",
    "email_verified_at": "...",
    "created_at": "..."
  },
  "claimed": {
    "reservations": 2,
    "restock_alerts": 1,
    "card_requests": 0
  }
}
```

Errors: generic `401` for invalid/expired code, `429` with `Retry-After`,
`403` for disabled accounts. Request errors never reveal account existence.

### Me

```http
GET /v1/me
```

Returns the customer profile.

```http
GET /v1/me/reservations
```

Returns up to 200 reservation summaries, newest first:

```json
{
  "id": "...",
  "public_ref": "R-ABC123",
  "status": "READY",
  "expires_at": "...",
  "created_at": "...",
  "total": { "amount_minor": 2500, "currency": "RSD" },
  "shop": { "slug": "bolt-shop", "name": "Bolt Shop" }
}
```

```http
GET /v1/me/reservations/{id}
POST /v1/me/reservations/{id}/cancel
```

Both return the full existing `ReservationOut` shape, with no access token.
Ownership is checked by `customer_id`; the detail handler sets the tenant
context only after resolving the customer-owned row.

```http
GET /v1/me/card-requests
GET /v1/me/card-requests/{id}
POST /v1/me/card-requests/{id}/accept
POST /v1/me/card-requests/{id}/cancel
```

The account response is the existing special-order shape plus a `shop` object.
Guest-token endpoints remain unchanged.

```http
GET /v1/me/restock-alerts
```

Returns alerts with `shop`, card name/set/number, variant, `stock_id` (nullable),
email, `created_at`, and `notified_at`.

```http
DELETE /v1/me/restock-alerts/{id}
204
```

The signed guest unsubscribe endpoints and `manage_token` behavior stay as they
are.

### Public create endpoints

`POST /v1/shops/{slug}/reservations`, `/restock-alerts`, and `/card-requests`
accept an optional customer Bearer token. If present:

- validate it with the same customer dependency;
- attach `customer_id`;
- use the account email.

No token means the current guest behavior, unchanged.

## 8. Tenant and RLS boundaries

- Customer JWT has no tenant context.
- `/v1/me` list endpoints set `app.customer_id`; tenant RLS is not needed for
  the customer-owned rows.
- `/v1/me` detail endpoints resolve the row with `app.customer_id`, then set
  `app.tenant_id` to load reservation lines.
- Claiming iterates tenants and sets `app.tenant_id` for each update.
- `users` gains a global-row policy; staff rows remain tenant-scoped and staff
  queries continue to filter by tenant.
- `customer_otp_challenges` is global like `cards`; it has no tenant RLS.
- Guest endpoints continue to set tenant context and authorize by access-token
  hash.

Postgres coverage proves:

- a customer context sees only its own rows across tenants;
- a customer context cannot see another customer's rows in the same tenant;
- a tenant context alone cannot see another tenant's rows;
- global customer login works without a tenant context;
- claim updates only unowned matching rows.

The Alembic `0004_customer_accounts` downgrade/upgrade round trip is verified
separately on PostgreSQL and SQLite.

## 9. Mobile UX and state

### Auth state

Add `AuthProvider` inside `QueryClientProvider`:

- token held only in memory; no account token in SecureStore or AsyncStorage;
- a cold app launch has no token and therefore starts signed out;
- backgrounding and reopening the same app process keeps the in-memory token
  until the 12-hour server expiry;
- key `cardtracker.auth-token.v1` is not used; guest tokens keep their existing
  storage;
- no launch restore; the token is set only after a successful verify in this
  app process;
- `401` clears the token;
- `requestCode(email)` and `verifyCode(email, code)`;
- `signOut()` removes the token and account query cache;
- expose `customer`, `token`, `hydrated`, `isAuthenticated`.

### Account screen

Add `/account`:

- signed out: email field -> "Send code" -> code field -> "Verify";
- countdown before resend; show validation/rate-limit errors;
- explain that guest holds, alerts, and special orders with the same email will
  be linked;
- after verification, show claimed counts;
- signed in: account email, linked-data counts, "Refresh", "Sign out";
- development-only debug code display when the API returns one.

Add an account/sign-in entry point on the home hero.

### Account data

Use React Query hooks for `/v1/me` lists, enabled only when signed in. Do not
write account data into the existing guest AsyncStorage stores.

Home, alerts, and special-order lists combine:

1. account rows from `/v1/me`;
2. device-local guest rows.

Deduplicate by id, with the account row preferred. This means:

- cross-device rows appear while signed in;
- local guest rows still appear when signed out;
- sign-out removes account-only rows without deleting the device's guest data.

Detail screens:

- try the account detail endpoint when signed in;
- fall back to the local guest row/token when the account does not own it;
- use account accept/cancel/unsubscribe when the row came from `/v1/me`;
- use the existing guest-token action otherwise.

Create forms:

- when signed in, show the account email as locked and send the Bearer token;
- when signed out, keep the current email input and guest flow.

### Not in this slice

- offline caching of account data;
- push notifications;
- account profile editing, email change, or deletion;
- account merge UI;
- admin customer lookup;
- universal/app links for account emails.

## 10. Security and privacy notes

- OTP plaintext never reaches the database or logs.
- Request and verify responses are deliberately generic to prevent account
  enumeration.
- A 6-digit code has 5 attempts and two layers of rate limiting.
- A new request consumes the previous challenge before creating a replacement,
  so only the newest code is redeemable on the normal request path.
- The worker stores only exception type/SMTP status in `email_error`.
- Debug codes are available only outside production.
- Email is the identity key. Anyone who controls the email can claim matching
  guest rows; that is the intended recovery mechanism, and it is why the OTP is
  required.
- Claimed rows keep their guest access token. On a shared device, signing out
  does not invalidate a previously saved guest token. This preserves the
  existing guest contract; a later "clear device data" control can address it.
- Rate limiting remains in-process; Redis is still a production hardening item.
- No refresh/revocation table yet; token lifetime and disabled-account checks
  are the current controls.

## 11. Tests and verification

Backend:

- OTP request creates a challenge and returns 202 for known and unknown emails;
- worker renders the derived code and marks the challenge sent;
- worker retries with backoff and does not resend consumed/expired challenges;
- verification creates a global account, sets `email_verified_at`, and returns
  a customer token;
- wrong/expired/exhausted codes fail; attempts are bounded;
- resend cooldown and rate limits;
- account email uniqueness is case-insensitive;
- account token works on `/v1/me`; staff and guest tokens do not;
- public create endpoints attach `customer_id` and use the account email when
  signed in;
- guest create flows remain unchanged;
- claim matches case-insensitively across shops, is idempotent, and never
  overwrites another owner;
- `/v1/me` lists and details return only the customer's rows across tenants;
- account cancel/accept/unsubscribe works;
- claimed restock alerts still work with the guest unsubscribe token;
- inactive accounts are rejected;
- Postgres RLS tests for global users, customer context, and claim scope.
- migration downgrade/upgrade verified on PostgreSQL and SQLite.

Mobile:

- TypeScript, ESLint, web export;
- guest browser smoke from the earlier Step 5 slice still passes;
- account UI/API coverage comes from the backend suites. A signed-in manual
  smoke is still required before release:
  - guest hold -> sign in -> claim -> sign out -> guest still visible;
  - second browser/device sign-in sees the same account data;
  - account-only hold detail/cancel works;
  - account alert unsubscribe and special-order accept/cancel work;
  - guest-only flows still work.

Docs:

- update `README.md`, `STATUS.md`, `SECURITY.md`, `backend/README.md`,
  `mobile/README.md`, and `.env.example`;
- refresh `admin/openapi.json` and generated admin/mobile types.

## 12. Rollout and rollback

Rollout:

1. Deploy migration and backend.
2. Deploy the worker (it now also drains OTP challenges).
3. Refresh OpenAPI/types.
4. Deploy admin/mobile.
5. Run SQLite and Postgres suites, then manual smoke.

No data backfill is needed. Existing guest rows stay unowned until a customer
verifies that email.

Rollback:

- stop creating accounts/claims;
- downgrade the migration (drop the OTP table/indexes and the added customer
  policies; the original tenant-only policies stay in place);
- global customer rows remain in `users` but become inaccessible until the
  schema is upgraded again.
