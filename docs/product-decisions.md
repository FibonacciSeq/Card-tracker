# Product decisions — account lifecycle and special-order pricing

Status: **accepted 2026-11-07**, before the vendor pilot.

This note closes the account-UX and special-order pricing questions from the
Step 5 release checklist. It is the source of truth for the customer-facing copy
in the mobile app and for the staff-facing conversion copy in the admin.

## 1. Account lifecycle

### 1.1 Sign out on this device

The mobile app sends its access token and the current device's refresh token to
`POST /v1/auth/logout`.

- The backend revokes only the matching refresh-token row. Other devices keep
  their refresh sessions and stay signed in.
- The app removes both stored tokens and the account query cache on this
  device. Device-local guest holds, alerts, special-order tokens, and cart data
  are not deleted.
- The access JWT is not server-revocable per session, so a copied access token
  could still be accepted until its 12-hour expiry. The app deletes its copy,
  and the session can no longer be refreshed.
- If the network call fails, the local session is still cleared. The server-side
  refresh token then expires on its normal 7-day schedule. Use **Sign out all
  devices** while online when a server-side revocation is required.

The logout request body is optional for older clients: when no refresh token is
sent, the backend keeps the previous account-wide revocation behavior.

### 1.2 Sign out everywhere

`POST /v1/me/sessions/revoke-all` revokes every refresh token for the account.

- Every device is signed out after its current access token expires and can no
  longer refresh immediately.
- Already-issued access tokens remain valid until their 12-hour expiry, because
  access tokens are stateless JWTs. This is the same limit as a normal sign-out,
  applied to every device.
- The current device also clears its stored tokens and account query cache.
  Device-local guest data remains.

The mobile confirmation copy says "Every device using this account is signed
out and can no longer refresh its session" rather than claiming instant JWT
invalidation.

### 1.3 Delete account

`DELETE /v1/me` is a **soft close**, not a hard delete. This is deliberate so
shops keep the reservation and special-order history they need for operations
and accounting.

What happens:

| Area | Result |
| --- | --- |
| Account status | The customer row is deactivated (`is_active = false`); it is not physically deleted |
| Sign-in | OTP verification for the same email returns `403 This account is unavailable.` The email is not reusable through the app |
| Sessions | Every refresh token is revoked. Every protected request using an old access token is rejected immediately because `is_active` is checked while resolving the customer |
| Notifications | Email and push delivery stop because the worker only delivers to active customers; queued rows are recorded as skipped |
| Shop records | Reservations, special orders, and restock alerts stay with their tenants and keep the `customer_id` link. They are not reassigned to another account |
| Account profile | Display name, phone, email, and the customer audit history remain in the database. A support-assisted erasure process is still required for a full data-deletion request |
| Device-local data | Guest tokens and guest rows saved on this device remain. The signed-in account cache and stored access/refresh tokens are removed |
| Recovery | There is no self-service reactivation. Re-enabling the account is a support/database action |

Customer-facing copy uses "Delete account" as the action label but explains that
it closes the account, signs out every device, keeps shop history, and leaves
device-local guest data in place. The success message is "Your account is closed
and every device is signed out. Guest items saved on this device remain
available."

### 1.4 Email change

Email change is an identity change, not a security event on shop data:

- the new address must prove ownership with a code sent to that address;
- an address already owned by another account is rejected;
- every existing refresh session is revoked, and the current device receives a
  fresh token pair;
- unowned guest rows matching the new address are claimed;
- device-local guest data is not deleted.

## 2. Special-order conversion pricing

### Decision

An accepted quote is **indicative**. When staff convert an accepted special
order into a reservation, the new hold uses the **current shelf price** of the
matching stock row.

### Rationale

- Special orders are sourcing requests. The shop quotes before it owns the card,
  and the card may be acquired later at a different market cost.
- Conversion creates an ordinary reservation tied to a stock row. Using the
  shelf price keeps stock, reservations, and in-store pricing consistent.
- The platform does not take payment or hold funds, so the quote is not a
  financial contract. A store that wants to change the price can decline and
  re-quote before conversion.

### Customer-facing copy

- A quote card is labelled as an indicative quote and says: "When the shop
  converts it, the hold uses the card's current shelf price."
- The accepted state says the shop will reserve the card at its current shelf
  price.
- The converted state points the customer at the new reservation reference so
  they can open the hold and see its total.

### Staff-facing copy

- The quote form says the price is indicative and conversion uses the shelf
  price.
- The convert form says the card must already be in stock for the same variant
  and that the hold uses the current shelf price.
- The special-orders page repeats that quotes are not price locks.

### Follow-up before a larger rollout

If pilot shops ask for price locks, implement them explicitly: store a quote
currency and per-copy price snapshot, show the price difference at conversion,
and require an explicit confirmation before creating the hold. Do not make the
quote authoritative implicitly.
