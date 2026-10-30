"""Notification outbox helpers and plain-text message rendering.

Notifications are queued inside the same transaction as the business event.
The delivery worker (``app.workers.notifications``) drains them later, so a
slow SMTP server never slows down a reservation.
"""

from __future__ import annotations

import uuid

from app import models
from app.config import settings
from app.security import restock_unsubscribe_token


def enqueue(
    db,
    tenant_id: uuid.UUID,
    kind: str,
    payload: dict,
    *,
    recipient: str | None = None,
    user_id: uuid.UUID | None = None,
) -> models.Notification:
    row = models.Notification(
        tenant_id=tenant_id,
        kind=kind,
        payload=payload,
        recipient=recipient,
        user_id=user_id,
        channel="email" if recipient else "in_app",
    )
    db.add(row)
    return row


def shop_label(tenant: models.Tenant) -> str:
    if tenant.settings and tenant.settings.brand_name:
        return tenant.settings.brand_name
    return tenant.name


def staff_recipient(tenant: models.Tenant) -> str | None:
    """Best available inbox for staff alerts.

    ``notification_email`` is the explicit setting; fall back to the public
    contact email so a newly seeded shop is not silently alert-less.
    """
    if not tenant.settings:
        return None
    contact = tenant.settings.contact or {}
    email = contact.get("email") if isinstance(contact, dict) else None
    return tenant.settings.notification_email or (str(email).strip() if email else None) or None


def _money(amount_minor: int | None, currency: str | None) -> str:
    if amount_minor is None:
        return "—"
    return f"{amount_minor / 100:.2f} {currency or ''}".strip()


def _when(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("T", " ")[:16] + " UTC"


def app_card_url(tenant: models.Tenant, payload: dict) -> str:
    """Deep link that opens the card (or shop) in the customer app."""
    slug = str(payload.get("shop_slug") or tenant.slug)
    stock_id = payload.get("stock_id")
    if stock_id:
        return f"cardtracker://shop/{slug}/card/{stock_id}"
    return f"cardtracker://shop/{slug}"


def unsubscribe_url(
    row: models.Notification,
    tenant: models.Tenant,
    *,
    one_click: bool = False,
) -> str | None:
    payload = row.payload or {}
    alert_id = payload.get("alert_id")
    if not alert_id:
        return None
    token = restock_unsubscribe_token(tenant.id, str(alert_id))
    slug = payload.get("shop_slug") or tenant.slug
    base = settings.public_api_url.rstrip("/")
    action = "unsubscribe/one-click" if one_click else "unsubscribe"
    return f"{base}/v1/shops/{slug}/restock-alerts/{alert_id}/{action}?token={token}"


def headers(row: models.Notification, tenant: models.Tenant) -> dict[str, str]:
    """Extra transport headers for one queued notification."""
    if row.kind != "RESTOCK_AVAILABLE":
        return {}
    url = unsubscribe_url(row, tenant, one_click=True)
    if not url:
        return {}
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def render_otp(code: str, expires_seconds: int) -> tuple[str, str]:
    """Render an OTP email without putting the code in a queue payload."""
    subject = "Your Card Tracker sign-in code"
    minutes = max(1, expires_seconds // 60)
    body = (
        f"Your sign-in code is: {code}\n\n"
        f"It expires in {minutes} minute(s). If you did not request this code, "
        f"you can ignore this email."
    )
    return subject, body


def render(row: models.Notification, tenant: models.Tenant) -> tuple[str, str]:
    """Return (subject, body) for one queued notification."""
    payload = row.payload or {}
    shop = shop_label(tenant)
    ref = payload.get("public_ref", "")
    kind = row.kind

    if kind == "RESERVATION_CREATED":
        subject = f"New reservation {ref} at {shop}"
        body = (
            f"{payload.get('customer_name', 'A customer')} requested "
            f"{payload.get('line_count', 0)} card line(s).\n\n"
            f"Reservation: {ref}\n"
            f"Total: {_money(payload.get('total_minor'), payload.get('currency'))}\n"
            f"Hold expires: {_when(payload.get('expires_at'))}\n\n"
            f"Open the admin to confirm it."
        )
        return subject, body

    if kind == "RESERVATION_CONFIRMED":
        subject = f"Reservation {ref} confirmed"
        body = (
            f"Good news — your reservation {ref} at {shop} is confirmed.\n"
            f"Please collect it before {_when(payload.get('expires_at'))}."
        )
        return subject, body

    if kind == "RESERVATION_READY":
        subject = f"Your cards are ready — {ref}"
        body = (
            f"Your reservation {ref} at {shop} is ready for pickup.\n"
            f"We will hold it until {_when(payload.get('expires_at'))}."
        )
        return subject, body

    if kind == "RESERVATION_CANCELLED":
        subject = f"Reservation {ref} cancelled"
        body = f"Reservation {ref} at {shop} has been cancelled and the cards released."
        return subject, body

    if kind == "RESERVATION_EXPIRED":
        subject = f"Reservation {ref} expired"
        body = (
            f"The hold on reservation {ref} at {shop} has expired and the cards were released.\n"
            f"Reserve them again in the app if you still want them."
        )
        return subject, body

    if kind == "RESERVATION_COMPLETED":
        subject = f"Thanks for collecting {ref}"
        body = f"Reservation {ref} at {shop} is complete. The cards are now marked as sold."
        return subject, body

    if kind == "CARD_REQUEST_CREATED":
        subject = f"Special-order request {ref} at {shop}"
        body = (
            f"{payload.get('customer_name', 'A customer')} asked for "
            f"{payload.get('quantity', 1)} x {payload.get('requested_name', 'a card')}.\n\n"
            f"Reference: {ref}\n"
            f"Customer note: {payload.get('customer_note') or '—'}\n\n"
            f"Open the admin to quote or decline."
        )
        return subject, body

    if kind == "CARD_REQUEST_QUOTED":
        subject = f"We found your card — quote for {ref}"
        body = (
            f"{shop} can source {payload.get('requested_name', 'your card')} "
            f"({payload.get('finish', 'nonfoil')}, {payload.get('condition', 'NM')}).\n\n"
            f"Quote: {_money(payload.get('quote_price_minor'), payload.get('currency'))}\n"
            f"Valid until: {_when(payload.get('quote_expires_at'))}\n"
            f"Note from the shop: {payload.get('vendor_note') or '—'}\n\n"
            f"Accept or cancel the quote in the app."
        )
        return subject, body

    if kind == "CARD_REQUEST_EXPIRED":
        subject = f"Your quote for {ref} expired"
        body = (
            f"The quote for {payload.get('requested_name', 'your card')} at {shop} has expired.\n"
            f"Ask the shop for a fresh quote if you are still interested."
        )
        return subject, body

    if kind == "CARD_REQUEST_DECLINED":
        subject = f"Update on your request {ref}"
        body = (
            f"{shop} could not source {payload.get('requested_name', 'your card')} this time.\n\n"
            f"Note from the shop: {payload.get('vendor_note') or '—'}"
        )
        return subject, body

    if kind == "CARD_REQUEST_ACCEPTED":
        subject = f"Customer accepted quote {ref}"
        body = (
            f"{payload.get('customer_name', 'The customer')} accepted the quote for "
            f"{payload.get('requested_name', 'a card')}.\n\n"
            f"Reference: {ref}\n"
            f"Source the card, add it to stock, then convert the request to a reservation."
        )
        return subject, body

    if kind == "CARD_REQUEST_CONVERTED":
        subject = f"Your special order {ref} is reserved"
        body = (
            f"The card you asked for is in and reserved under {payload.get('reservation_ref', '')}.\n"
            f"Please collect it before {_when(payload.get('expires_at'))}."
        )
        return subject, body

    if kind == "RESTOCK_AVAILABLE":
        subject = f"Back in stock at {shop}: {payload.get('name', 'a card')}"
        link = app_card_url(tenant, payload)
        unsubscribe = unsubscribe_url(row, tenant)
        body = (
            f"{payload.get('name', 'A card')} ({payload.get('finish', 'nonfoil')}, "
            f"{payload.get('condition', 'NM')}, {payload.get('language', 'en')}) is available again.\n\n"
            f"Price: {_money(payload.get('price_minor'), payload.get('currency'))}\n"
            f"Reserve it in the {shop} app: {link}\n"
        )
        if unsubscribe:
            body += f"\nYou asked {shop} to tell you when this card returned.\nUnsubscribe: {unsubscribe}\n"
        return subject, body

    return f"{shop}: {kind}", str(payload)
