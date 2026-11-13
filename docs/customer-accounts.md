# Customer accounts and guest-data claiming

Status: **implemented** on 2026-10-29; extended 2026-11-06 with refresh
sessions, revoke-all, email change, customer account audit events, a customer
notification delivery log, and push-token diagnostics. Account lifecycle copy
and special-order pricing were settled on 2026-11-07 in
[`product-decisions.md`](product-decisions.md).

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
| Session token | HS256 JWT, 12 hours, persisted in secure device storage |
| Refresh token | Opaque server-side token, 7 days, rotates on use; logout revokes the current device's token when supplied, revoke-all revokes every session |
| Email change | New address must prove ownership with an OTP before the account email changes |
| Account audit | Customer-scoped rows in `customer_audit_events`, separate from tenant audit |
| Mobile account data | Fetched from `/v1/me` and held in React Query; not merged into guest AsyncStorage |
| Sign-out | Revoke this device's refresh session, remove account tokens and query cache; leave other devices and device-local guest rows alone |
| Sign out everywhere | Revoke every refresh session, then remove this device's tokens and account cache |
| Delete account | Soft-close the account, revoke every session, keep shop history and device-local guest rows; see the lifecycle matrix |
| App launch | Restore the persisted session, then refresh or return to sign-in if it is invalid |

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

### 3.4 Customer notification delivery log

Reuse the existing tenant `notifications` outbox as the customer-facing delivery
log instead of adding a duplicate notification table. Every queued email, push,
or in-app row already carries `user_id`, `kind`, `payload`, `channel`,
`attempts`, `sent_at`, `next_attempt_at`, and a sanitized `error`.

Add an index on `(user_id, id)` for the account log cursor, and on Postgres a
permissive `notifications_customer_own` policy:

```sql
FOR SELECT
USING (
  user_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
)
```

The policy is read-only on purpose. The existing tenant policy remains, so the
notification worker still drains a tenant's outbox. A missing context still sees
no rows.

Push-token diagnostics live on `push_tokens`:

| Column | Purpose |
| --- | --- |
| `failure_count` | Number of failed provider attempts for this token |
| `last_failure_at` | Time of the most recent failure |
| `last_error` | Exception type and sanitized provider message, never the device token |

The worker increments these fields for transient and invalid-token failures.
An invalid token is also marked with `revoked_at`; a later registration of the
same device/token can reactivate it. The raw device token is never returned by
the account API.

Alembic `0008_customer_notifications` adds the diagnostics columns, the
notification index, and the Postgres customer policy. Its downgrade drops the
policy and index and removes the columns. The migration runner widens
`alembic_version.version_num` to 64 characters on Postgres so the existing
38-character `0006_customer_notification_preferences` revision id round-trips.

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

Token lifetime is 12 hours. The backend also issues a server-side opaque refresh
token with a 7-day lifetime; refresh tokens rotate on use and are revoked on
logout (the current device when its token is supplied), `POST
/v1/me/sessions/revoke-all`, account deletion, and email change.
The mobile app persists both tokens in secure device storage, restores the
session on cold launch, and swaps in the rotated pair after a refresh. A failed
refresh clears the stored session. Disabling an account takes effect on the next
request because `is_active` is checked.

Email change uses the OTP challenge store with a non-null `user_id`:

```text
POST /v1/me/email         -> send a code to the requested new address
POST /v1/me/email/verify  -> move the account email after proving ownership
```

Verification rejects addresses already owned by another account, revokes every
refresh session, issues a fresh token pair to the current device, claims unowned
guest rows matching the new email, and records a customer audit event. Login
verification only redeems challenges with `user_id IS NULL`; email-change
verification only redeems the current customer's non-null challenge.

## 6. Guest claiming

On every successful login verification, for each tenant:

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
- Email change re-runs claiming for the new address after the change commits, so
  guest rows created with the new email are linked to the same account.

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

All `/v1/me` endpoints and `/v1/auth/logout` require
`Authorization: Bearer <customer token>` and return `Cache-Control: no-store`.
OTP request/verify and refresh are unauthenticated credential exchanges.

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
  "refresh_token": "...",
  "refresh_expires_in": 604800,
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

```http
POST /v1/auth/refresh
{ "refresh_token": "..." }
```

Returns the same token shape as verify. Refresh tokens rotate; a replayed token
is rejected. Requesting a new OTP does not revoke existing sessions.

```http
POST /v1/auth/logout
{ "refresh_token": "..." }

204
```

Requires a customer token. With a refresh token in the body, only that device's
session is revoked. Omitting the body keeps the legacy account-wide behavior
and revokes every refresh token.

```http
POST /v1/me/sessions/revoke-all
204
```

Requires a customer token and revokes every refresh token for the account.

### Me

```http
GET /v1/me
```

Returns the customer profile.

```http
PATCH /v1/me
{ "display_name": "...", "phone": "...", "push_notifications_enabled": true }
```

Updates the profile and notification preferences, returning the customer profile.

```http
DELETE /v1/me
204
```

Deactivates the account (soft close), revokes every refresh token, stops
notification delivery, records a customer audit event, and leaves shop records
intact. The same email cannot sign in again unless support reactivates the
account. The full outcome matrix is in
[`product-decisions.md`](product-decisions.md#13-delete-account).

```http
POST /v1/me/email
{ "email": "new@example.com" }

202 {
  "expires_in": 600,
  "resend_after": 60,
  "debug_code": null
}
```

```http
POST /v1/me/email/verify
{ "email": "new@example.com", "code": "123456" }
```

Returns the same token shape as verify, with a new access/refresh pair for the
current device. The new address must not belong to another account.

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

```http
GET /v1/me/notifications?limit=50&cursor=123
```

Returns the customer's delivery log newest first. `limit` is 1–200; `cursor`
is the previous page's last numeric notification id. One business event may
appear once per channel (for example, email and push), because each queued
delivery row is shown separately.

```json
{
  "items": [
    {
      "id": 123,
      "kind": "RESERVATION_READY",
      "channel": "push",
      "status": "sent",
      "title": "Your cards are ready — R-ABC123",
      "shop": { "slug": "bolt-shop", "name": "Bolt Shop" },
      "attempts": 1,
      "created_at": "...",
      "sent_at": "...",
      "next_attempt_at": null,
      "error": null
    }
  ],
  "next_cursor": null
}
```

Statuses are derived from the outbox row:

| Status | Meaning |
| --- | --- |
| `pending` | Queued and not attempted yet |
| `retrying` | At least one failed attempt; the worker will retry after `next_attempt_at` |
| `sent` | Delivered without an error |
| `skipped` | Preferences disabled delivery or the customer has no active push token |
| `failed` | Delivery stopped with a non-skipped error |

In-app rows are recorded for this log; they are not sent by the email/push
worker. Only the rendered title is returned, not the body, so restock
unsubscribe tokens cannot leak through the account API. `error` is the stored
sanitized delivery error and never contains a recipient, message body, or device
token. Rows whose tenant no longer exists are skipped.

```http
GET /v1/me/push-tokens
```

Returns the customer's device registrations, newest first, including revoked
tokens:

```json
{
  "items": [
    {
      "id": "...",
      "platform": "android",
      "created_at": "...",
      "last_seen_at": "...",
      "revoked_at": null,
      "failure_count": 2,
      "last_failure_at": "...",
      "last_error": "PushTransientError: FCM transport failed"
    }
  ]
}
```

The existing `POST /v1/me/push-tokens` and `DELETE /v1/me/push-tokens/{token}`
endpoints are unchanged. Neither response returns the raw device token.

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
- `customer_audit_events` is global because one customer spans tenants; RLS
  limits rows to the active `app.customer_id`.
- `push_tokens` are customer-scoped and visible to the push worker context.
- `notifications` keeps its tenant policy and gains a permissive customer
  policy. Customer account reads therefore see only rows with the matching
  `user_id`, while the worker still drains a whole tenant's outbox.
- Guest endpoints continue to set tenant context and authorize by access-token
  hash.

Postgres coverage proves:

- a customer context sees only its own rows across tenants;
- a customer context cannot see another customer's rows in the same tenant;
- a tenant context alone cannot see another tenant's rows;
- global customer login works without a tenant context;
- claim updates only unowned matching rows;
- customer audit rows are isolated to their customer and reject cross-customer
  writes;
- customer notification rows are isolated across customers and tenants, while
  a tenant context still sees the tenant's whole notification outbox.

The Alembic `0008_customer_notifications` downgrade/upgrade round trip is
verified separately on PostgreSQL and SQLite. The customer notification RLS
policy and the push-token diagnostic columns are recreated on upgrade.

## 9. Mobile UX and state

### Auth state

Add `AuthProvider` inside `QueryClientProvider`:

- access and refresh tokens persist via SecureStore on native platforms and
  AsyncStorage on web;
- cold launch restores both tokens, validates them with `/v1/me`, and falls back
  to a refresh-token exchange when the access token is stale;
- the refresh handler rotates the stored tokens; a failed refresh signs out and
  clears local account cache;
- the guest token keys are unchanged;
- `401` attempts one refresh when a refresh token exists; a failed refresh signs
  out and clears local session state;
- `requestCode(email)` / `verifyCode(email, code)`;
- `requestEmailChange(email)` / `verifyEmailChange(email, code)`;
- `signOut()` sends the current refresh token, revokes this device's server
  session, removes both tokens, and removes the account query cache; local state
  is cleared even when the network call fails, and the server token then expires
  on its normal schedule;
- `signOutEverywhere()` calls `/v1/me/sessions/revoke-all`, then clears this
  device; if the request fails, the user stays signed in and sees the error;
- access tokens already issued to a signed-out device remain valid until their
  12-hour expiry because access JWTs are stateless; a deleted account is rejected
  on the next request because `is_active` is checked while resolving the
  customer;
- expose `customer`, `token`, `hydrated`, `isAuthenticated`.

### Account screen

Add `/account`:

- signed out: email field -> "Send code" -> code field -> "Verify";
- countdown before resend; show validation/rate-limit errors;
- explain that guest holds, alerts, and special orders with the same email will
  be linked;
- after verification, show claimed counts;
- signed in: account email, linked-data counts, profile and notification
  preferences, email change with a new-address code, "Refresh", "Sign out all
  devices", "Delete account", and "Sign out";
- destructive actions use a confirmation modal that states which devices and
  data are affected; a failure keeps the user signed in and shows the error;
- a "Notification delivery" card opens the delivery log and push-device status;
- development-only debug code display for login and email-change codes.

Add an account/sign-in entry point on the home hero.

### Account data

Use React Query hooks for `/v1/me` lists, enabled only when signed in. Do not
write account data into the existing guest AsyncStorage stores. The persisted
query cache can include account queries while signed in; sign-out removes
account queries from it.

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

### Notification delivery

Add `/notifications` as a signed-in account screen:

- summarize active and revoked push devices from `/v1/me/push-tokens`, including
  failure count, last failure time, and sanitized last error;
- list delivery rows from `/v1/me/notifications` with channel, status, rendered
  title, shop, timestamp, attempt count, and sanitized error;
- support pull-to-refresh and cursor-based "load older notifications";
- link back to Account for push enable/disable and notification preferences;
- show an empty state explaining that activity appears after the first hold,
  request, or restock alert is queued.

The screen does not expose push tokens, notification bodies, unsubscribe tokens,
or OTP data.

### Not in this slice

- a customer-facing audit/activity screen;
- an account merge conflict UI (automatic claiming is implemented);
- admin customer lookup;
- production universal-link validation and browser install cues.

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
- Refresh token secrets are stored hashed; the table supports per-session
  revocation and rotation. A replayed or expired refresh token is rejected.
- Logout with the current device's refresh token revokes only that row. A
  body-less logout keeps the legacy account-wide behavior for older clients.
- Access JWTs are stateless, so sign-out, sign-out-everywhere, and email change
  stop refresh immediately but cannot invalidate an already-copied access token
  before its 12-hour expiry. Account deletion and deactivation are stronger:
  `is_active` is checked while resolving the customer, so old access tokens are
  rejected on the next request.
- Account deletion is a soft close. It deactivates the customer row, revokes
  every refresh token, and stops notification delivery; shop history and
  profile/audit rows remain for operational and accounting needs. It is not a
  full erasure mechanism and does not remove device-local guest data.
- Email change requires control of both the current session and the new email.
  A target address owned by another account is rejected before a confirmation
  code is sent; the unauthenticated OTP request path stays deliberately generic.
- Customer audit rows store action metadata, never OTPs or token secrets. They
  are customer-scoped by RLS and are separate from tenant audit rows.
- The delivery log returns rendered titles only, not message bodies, so restock
  unsubscribe tokens are not exposed through `/v1/me/notifications`. Stored
  delivery errors are sanitized and contain no recipient, body, or device token.
- Push-token diagnostics store the failure count, time, and sanitized error. The
  raw FCM/APNs token is never returned by account endpoints, and an invalid
  provider token is revoked immediately.

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
- refresh tokens rotate and reject replay;
- logout with the current device's refresh token revokes only that session and
  leaves another device able to refresh; a body-less logout still revokes every
  session;
- revoke-all, deletion, and email change revoke every existing refresh session;
- a deleted or deactivated account is rejected on the next protected request,
  even with an otherwise valid access token;
- email change sends a challenge to the new address, rejects addresses owned by
  another account, handles expiry/attempts/cooldown, issues a fresh token pair,
  and re-claims matching guest rows;
- customer audit rows are written for login, refresh, logout, revoke-all,
  profile update, email change, and deletion;
- `/v1/me/notifications` returns only the customer's rows across tenants,
  paginates by id, computes all five delivery statuses, renders titles, skips
  orphaned tenant rows, validates query bounds, and requires auth;
- `/v1/me/push-tokens` returns only the customer's devices, including revoked
  tokens and failure diagnostics, and never returns the raw token;
- the push worker increments failure diagnostics for transient and invalid
  tokens, sets `revoked_at` for invalid tokens, and keeps the existing retry
  behavior;
- Postgres RLS tests for global users, customer context, claim scope, push
  tokens, customer audit rows, and notification rows.
- migration downgrade/upgrade verified on PostgreSQL and SQLite.

Mobile:

- TypeScript, ESLint, Vitest for `src/lib/**` at 100% statement/branch/function/
  line coverage;
- guest browser smoke from the earlier Step 5 slice still passes;
- account UI/API coverage comes from the backend suites. A signed-in manual
  smoke is still required before release:
  - guest hold -> sign in -> claim -> sign out -> guest still visible;
  - cold launch restores the session and rotates an expired access token;
  - second browser/device sign-in sees the same account data;
  - signing out one device leaves the other able to refresh; sign-out-all and
    account deletion stop both devices from refreshing;
  - account-only hold detail/cancel works;
  - account alert unsubscribe and special-order accept/cancel work;
  - email change signs out other devices, applies the new address, and keeps
    the current device signed in;
  - guest-only flows still work.

Docs:

- update `README.md`, `STATUS.md`, `SECURITY.md`, `backend/README.md`,
  `mobile/README.md`, and `.env.example`;
- refresh `admin/openapi.json` and the generated shared API types.

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
- downgrade `0008_customer_notifications` to drop the notification customer
  policy, the customer-log index, and the push-token diagnostic columns; the
  tenant notification policy and existing outbox rows stay in place;
- downgrade the earlier account migrations only if the whole account slice is
  being removed (drop the OTP table/indexes and the added customer policies; the
  original tenant-only policies stay in place);
- global customer rows remain in `users` but become inaccessible until the
  schema is upgraded again.
