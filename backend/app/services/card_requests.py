"""Special-order requests: ask, quote, accept, and convert to a hold.

No stock is held while a request is being sourced, and no price is promised
until the shop quotes one. Conversion happens only after the card is back in
stock, at which point it becomes an ordinary CONFIRMED reservation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import set_tenant_context
from app.security import hash_guest_token, new_guest_token, new_request_ref
from app.services import notifications
from app.services import reservations as reservation_service

ACTIVE_STATUSES = ("REQUESTED", "QUOTED", "ACCEPTED")
# An accepted quote should not sit forever if the shop never converts it.
ACCEPTED_EXPIRY_DAYS = 14


class CardRequestError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read, so normalise before Python comparisons."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _unique_ref(db: Session, tenant_id: uuid.UUID) -> str:
    for _ in range(10):
        ref = new_request_ref()
        exists = db.scalar(
            select(models.CardRequest.id).where(
                models.CardRequest.tenant_id == tenant_id,
                models.CardRequest.public_ref == ref,
            )
        )
        if not exists:
            return ref
    raise CardRequestError("ref_conflict", "Could not allocate a request reference.", 500)


def _notification_recipient(tenant: models.Tenant) -> str | None:
    return notifications.staff_recipient(tenant)


def create(
    db: Session,
    tenant: models.Tenant,
    payload: schemas.CardRequestCreateIn,
) -> tuple[models.CardRequest, str]:
    card = None
    if payload.card_id is not None:
        card = db.get(models.Card, payload.card_id)
        if card is None:
            raise CardRequestError("card_not_found", "That card is not in the catalog.", 404)

    name = payload.requested_name.strip() or (card.name if card else "")
    if not name:
        raise CardRequestError("name_required", "Tell us which card you need.", 422)

    token = new_guest_token()
    row = models.CardRequest(
        tenant_id=tenant.id,
        public_ref=_unique_ref(db, tenant.id),
        customer_name=payload.customer.name.strip(),
        email=str(payload.customer.email).lower().strip(),
        phone=payload.customer.phone.strip(),
        card_id=card.id if card else None,
        requested_name=name,
        set_code=(payload.set_code.strip() or (card.set_code if card else "")).upper(),
        collector_number=(payload.collector_number.strip() or (card.collector_number if card else "")).upper(),
        finish=payload.finish,
        condition=payload.condition,
        language=payload.language.lower(),
        quantity=payload.quantity,
        target_price_minor=payload.target_price_minor,
        currency=tenant.currency,
        customer_note=payload.note.strip(),
        status="REQUESTED",
        access_token_hash=hash_guest_token(token),
    )
    db.add(row)
    db.flush()

    notifications.enqueue(
        db,
        tenant.id,
        "CARD_REQUEST_CREATED",
        {
            "public_ref": row.public_ref,
            "customer_name": row.customer_name,
            "requested_name": row.requested_name,
            "quantity": row.quantity,
            "customer_note": row.customer_note,
        },
        recipient=_notification_recipient(tenant),
    )
    db.commit()
    db.refresh(row)
    return row, token


def get_authorized(
    db: Session,
    tenant: models.Tenant,
    request_id: uuid.UUID,
    token: str | None,
) -> models.CardRequest:
    row = db.scalar(
        select(models.CardRequest).where(
            models.CardRequest.id == request_id,
            models.CardRequest.tenant_id == tenant.id,
        )
    )
    if row is None:
        raise CardRequestError("not_found", "Request not found.", 404)
    if not token or row.access_token_hash != hash_guest_token(token):
        raise CardRequestError("invalid_token", "Invalid request token.", 403)
    return row


def quote(
    db: Session,
    tenant: models.Tenant,
    row: models.CardRequest,
    payload: schemas.QuoteIn,
) -> models.CardRequest:
    if row.status not in ("REQUESTED", "QUOTED"):
        raise CardRequestError("invalid_status", f"Cannot quote a {row.status.lower()} request.", 409)

    quote_expires_at = _as_utc(payload.quote_expires_at)
    if quote_expires_at is not None and quote_expires_at <= _now():
        raise CardRequestError("invalid_expiry", "The quote expiry must be in the future.", 422)

    row.quote_price_minor = payload.quote_price_minor
    row.quote_currency = tenant.currency
    row.quote_expires_at = payload.quote_expires_at
    row.vendor_note = payload.vendor_note.strip()
    row.status = "QUOTED"
    row.updated_at = _now()

    notifications.enqueue(
        db,
        tenant.id,
        "CARD_REQUEST_QUOTED",
        {
            "public_ref": row.public_ref,
            "requested_name": row.requested_name,
            "finish": row.finish,
            "condition": row.condition,
            "quote_price_minor": row.quote_price_minor,
            "currency": row.quote_currency,
            "quote_expires_at": row.quote_expires_at.isoformat() if row.quote_expires_at else None,
            "vendor_note": row.vendor_note,
        },
        recipient=row.email,
    )
    db.commit()
    db.refresh(row)
    return row


def decline(db: Session, tenant: models.Tenant, row: models.CardRequest, note: str) -> models.CardRequest:
    if row.status not in ("REQUESTED", "QUOTED", "ACCEPTED"):
        raise CardRequestError("invalid_status", f"Cannot decline a {row.status.lower()} request.", 409)

    row.status = "DECLINED"
    row.vendor_note = note.strip()
    row.updated_at = _now()
    notifications.enqueue(
        db,
        tenant.id,
        "CARD_REQUEST_DECLINED",
        {
            "public_ref": row.public_ref,
            "requested_name": row.requested_name,
            "vendor_note": row.vendor_note,
        },
        recipient=row.email,
    )
    db.commit()
    db.refresh(row)
    return row


def accept(db: Session, tenant: models.Tenant, row: models.CardRequest) -> models.CardRequest:
    now = _now()
    expires_at = _as_utc(row.quote_expires_at)
    if row.status == "QUOTED" and expires_at is not None and expires_at <= now:
        row.status = "EXPIRED"
        row.updated_at = now
        notifications.enqueue(
            db,
            tenant.id,
            "CARD_REQUEST_EXPIRED",
            {"public_ref": row.public_ref, "requested_name": row.requested_name},
            recipient=row.email,
        )
        db.commit()
        raise CardRequestError("quote_expired", "This quote has expired. Ask the shop for a new one.", 409)
    if row.status != "QUOTED":
        raise CardRequestError("invalid_status", "This request is not awaiting a quote decision.", 409)

    row.status = "ACCEPTED"
    row.updated_at = now
    notifications.enqueue(
        db,
        tenant.id,
        "CARD_REQUEST_ACCEPTED",
        {
            "public_ref": row.public_ref,
            "customer_name": row.customer_name,
            "requested_name": row.requested_name,
        },
        recipient=_notification_recipient(tenant),
    )
    db.commit()
    db.refresh(row)
    return row


def cancel(db: Session, tenant: models.Tenant, row: models.CardRequest) -> models.CardRequest:
    if row.status not in ACTIVE_STATUSES:
        raise CardRequestError("invalid_status", f"Cannot cancel a {row.status.lower()} request.", 409)
    row.status = "CANCELLED"
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def convert(
    db: Session,
    tenant: models.Tenant,
    row: models.CardRequest,
    quantity: int | None = None,
) -> tuple[models.CardRequest, models.Reservation]:
    if row.status != "ACCEPTED":
        raise CardRequestError("invalid_status", "Only an accepted request can be converted.", 409)
    if row.card_id is None:
        raise CardRequestError(
            "no_catalog_card",
            "This request has no catalog card. Add the card to the catalog first.",
            409,
        )

    stock = db.scalar(
        select(models.Stock)
        .where(
            models.Stock.tenant_id == tenant.id,
            models.Stock.card_id == row.card_id,
            models.Stock.finish == row.finish,
            models.Stock.condition == row.condition,
            models.Stock.language == row.language,
        )
        .with_for_update()
    )
    if stock is None:
        raise CardRequestError(
            "stock_missing",
            "Add this exact card and variant to stock first, then convert the request.",
            409,
        )

    wanted = quantity if quantity is not None else row.quantity
    available = stock.quantity - stock.reserved
    if wanted > available:
        raise CardRequestError(
            "stock_short",
            f"Only {max(0, available)} available; add more stock or convert a smaller quantity.",
            409,
        )

    reservation, _token = reservation_service.create_staff_hold(
        db,
        tenant,
        stock=stock,
        quantity=wanted,
        customer_name=row.customer_name,
        email=row.email,
        phone=row.phone,
        note=f"Special order {row.public_ref}",
        source="staff",
    )

    row.status = "CONVERTED"
    row.reservation_id = reservation.id
    row.updated_at = _now()
    notifications.enqueue(
        db,
        tenant.id,
        "CARD_REQUEST_CONVERTED",
        {
            "public_ref": row.public_ref,
            "reservation_ref": reservation.public_ref,
            "expires_at": reservation.expires_at.isoformat(),
        },
        recipient=row.email,
    )
    db.commit()
    db.refresh(row)
    db.refresh(reservation)
    return row, reservation


def expire_due_quotes(db: Session, now: datetime | None = None) -> int:
    now = now or _now()
    db.expire_all()
    tenants = list(db.scalars(select(models.Tenant)).all())
    expired = 0
    for tenant in tenants:
        set_tenant_context(db, tenant.id)
        due = list(
            db.scalars(
                select(models.CardRequest)
                .where(
                    models.CardRequest.tenant_id == tenant.id,
                    or_(
                        and_(
                            models.CardRequest.status == "QUOTED",
                            models.CardRequest.quote_expires_at.is_not(None),
                            models.CardRequest.quote_expires_at <= now,
                        ),
                        and_(
                            models.CardRequest.status == "ACCEPTED",
                            models.CardRequest.updated_at <= now - timedelta(days=ACCEPTED_EXPIRY_DAYS),
                        ),
                    ),
                )
                .with_for_update(skip_locked=True)
            ).all()
        )
        for row in due:
            row.status = "EXPIRED"
            row.updated_at = now
            notifications.enqueue(
                db,
                tenant.id,
                "CARD_REQUEST_EXPIRED",
                {"public_ref": row.public_ref, "requested_name": row.requested_name},
                recipient=row.email,
            )
            expired += 1
        if due:
            db.commit()
    return expired
