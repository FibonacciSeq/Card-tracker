"""Reservation engine: holds, releases, sales, and expiry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.db import set_tenant_context
from app.security import hash_guest_token, new_guest_token, new_public_ref

ACTIVE_STATUSES = ("REQUESTED", "CONFIRMED", "READY")
TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "EXPIRED")


class ReservationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _now() -> datetime:
    return datetime.now(UTC)


def _request_hash(payload: schemas.ReservationCreate) -> str:
    import hashlib
    import json

    raw = payload.model_dump(mode="json")
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()


def _lock_stocks(db: Session, tenant_id: uuid.UUID, stock_ids: set[uuid.UUID]) -> dict[uuid.UUID, models.Stock]:
    if not stock_ids:
        return {}
    stmt = (
        select(models.Stock)
        .where(models.Stock.tenant_id == tenant_id, models.Stock.id.in_(stock_ids))
        .order_by(models.Stock.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {stock.id: stock for stock in db.scalars(stmt).all()}


def _movement(
    *,
    tenant_id: uuid.UUID,
    stock: models.Stock,
    kind: str,
    on_hand_delta: int = 0,
    reserved_delta: int = 0,
    reservation_id: uuid.UUID | None = None,
    line_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> models.StockMovement:
    return models.StockMovement(
        tenant_id=tenant_id,
        stock_id=stock.id,
        reservation_id=reservation_id,
        line_id=line_id,
        kind=kind,
        on_hand_delta=on_hand_delta,
        reserved_delta=reserved_delta,
        on_hand_after=stock.quantity,
        reserved_after=stock.reserved,
        actor_id=actor_id,
        reason=reason,
    )


def create_reservation(
    db: Session,
    tenant: models.Tenant,
    payload: schemas.ReservationCreate,
    idempotency_key: str | None = None,
) -> tuple[models.Reservation, str | None]:
    request_hash = _request_hash(payload)

    if idempotency_key:
        existing = db.get(models.IdempotencyKey, idempotency_key)
        if existing is not None:
            if existing.tenant_id != tenant.id or existing.request_hash != request_hash:
                raise ReservationError(
                    "idempotency_conflict",
                    "This idempotency key was already used with different data.",
                    status_code=409,
                )
            reservation = db.get(models.Reservation, uuid.UUID(existing.response["reservation_id"]))
            if reservation is None:
                raise ReservationError("not_found", "Reservation not found.", status_code=404)
            return reservation, existing.response.get("access_token")

    quantities: dict[uuid.UUID, int] = {}
    for item in payload.items:
        quantities[item.stock_id] = quantities.get(item.stock_id, 0) + item.quantity

    now = _now()
    access_token = new_guest_token()

    try:
        stocks = _lock_stocks(db, tenant.id, set(quantities))

        missing = [str(stock_id) for stock_id in quantities if stock_id not in stocks]
        if missing:
            raise ReservationError(
                "stock_not_found",
                "Some cards are no longer in this shop.",
                status_code=404,
                details={"stock_ids": missing},
            )

        conflicts: list[dict] = []
        for stock_id, requested in quantities.items():
            stock = stocks[stock_id]
            if not stock.is_online:
                conflicts.append(
                    {"stock_id": str(stock_id), "requested": requested, "available": 0, "reason": "offline"}
                )
                continue
            if stock.currency != tenant.currency:
                raise ReservationError(
                    "currency_mismatch",
                    "This shop has an inconsistent currency configuration.",
                    status_code=500,
                )
            available = stock.quantity - stock.reserved
            # v1 has no automatic customer backorders. The owner-facing
            # backorder flag is reserved for a later release and must not allow
            # reserved to exceed on-hand stock yet.
            if requested > available:
                conflicts.append({"stock_id": str(stock_id), "requested": requested, "available": max(0, available)})

        if conflicts:
            raise ReservationError(
                "stock_changed",
                "Some cards are no longer available in the requested quantity.",
                status_code=409,
                details={"lines": conflicts},
            )

        hold_hours = tenant.settings.hold_hours if tenant.settings else settings.default_hold_hours
        public_ref = _unique_public_ref(db, tenant.id)

        reservation = models.Reservation(
            tenant_id=tenant.id,
            public_ref=public_ref,
            customer_name=payload.customer.name.strip(),
            email=str(payload.customer.email).lower().strip(),
            phone=payload.customer.phone.strip(),
            note=payload.note.strip(),
            status="REQUESTED",
            total_minor=0,
            currency=tenant.currency,
            expires_at=now + timedelta(hours=hold_hours),
            source="app",
            access_token_hash=hash_guest_token(access_token),
        )
        db.add(reservation)
        db.flush()

        total = 0
        for stock_id, requested in quantities.items():
            stock = stocks[stock_id]
            card = db.get(models.Card, stock.card_id)
            if card is None:
                raise ReservationError("card_not_found", "Card catalog entry is missing.", status_code=500)

            line = models.ReservationLine(
                tenant_id=tenant.id,
                reservation_id=reservation.id,
                stock_id=stock.id,
                card_id=card.id,
                name=card.name,
                set_code=card.set_code,
                collector_number=card.collector_number,
                finish=stock.finish,
                condition=stock.condition,
                language=stock.language,
                quantity=requested,
                unit_price_minor=stock.price_minor,
                currency=stock.currency,
            )
            db.add(line)
            db.flush()

            total += stock.price_minor * requested
            stock.reserved += requested
            stock.updated_at = now
            db.add(
                _movement(
                    tenant_id=tenant.id,
                    stock=stock,
                    kind="RESERVE",
                    reserved_delta=requested,
                    reservation_id=reservation.id,
                    line_id=line.id,
                    reason="reservation created",
                )
            )

        reservation.total_minor = total
        reservation.updated_at = now
        db.add(
            models.Notification(
                tenant_id=tenant.id,
                kind="RESERVATION_CREATED",
                payload={
                    "reservation_id": str(reservation.id),
                    "public_ref": reservation.public_ref,
                    "customer_name": reservation.customer_name,
                    "line_count": len(quantities),
                },
            )
        )

        if idempotency_key:
            db.add(
                models.IdempotencyKey(
                    key=idempotency_key,
                    tenant_id=tenant.id,
                    endpoint="POST /v1/shops/{slug}/reservations",
                    request_hash=request_hash,
                    status=201,
                    response={
                        "reservation_id": str(reservation.id),
                        "access_token": access_token,
                    },
                    expires_at=now + timedelta(hours=24),
                )
            )

        db.commit()
        db.refresh(reservation)
        return reservation, access_token

    except IntegrityError as exc:
        db.rollback()
        if idempotency_key:
            existing = db.get(models.IdempotencyKey, idempotency_key)
            if existing is not None and existing.request_hash == request_hash:
                reservation = db.get(models.Reservation, uuid.UUID(existing.response["reservation_id"]))
                if reservation is not None:
                    return reservation, existing.response.get("access_token")
        raise ReservationError("conflict", "The reservation could not be created.", status_code=409) from exc
    except Exception:
        db.rollback()
        raise


def _unique_public_ref(db: Session, tenant_id: uuid.UUID) -> str:
    for _ in range(10):
        ref = new_public_ref()
        exists = db.scalar(
            select(models.Reservation.id).where(
                models.Reservation.tenant_id == tenant_id,
                models.Reservation.public_ref == ref,
            )
        )
        if exists is None:
            return ref
    raise ReservationError("ref_generation_failed", "Could not allocate a reservation reference.", status_code=500)


def get_reservation(db: Session, tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> models.Reservation:
    reservation = db.scalar(
        select(models.Reservation).where(
            models.Reservation.id == reservation_id,
            models.Reservation.tenant_id == tenant_id,
        )
    )
    if reservation is None:
        raise ReservationError("not_found", "Reservation not found.", status_code=404)
    return reservation


def _release(
    db: Session,
    reservation: models.Reservation,
    *,
    new_status: str,
    reason: str | None,
    actor_id: uuid.UUID | None,
) -> None:
    if reservation.status in TERMINAL_STATUSES:
        raise ReservationError("invalid_state", "This reservation is already closed.", status_code=409)

    stocks = _lock_stocks(db, reservation.tenant_id, {line.stock_id for line in reservation.lines})
    for line in reservation.lines:
        remaining = line.remaining
        if remaining <= 0:
            continue
        stock = stocks[line.stock_id]
        if stock.reserved < remaining:
            raise ReservationError(
                "stock_inconsistency",
                "Reserved stock is lower than the reservation expects.",
                status_code=500,
            )
        stock.reserved -= remaining
        stock.updated_at = _now()
        line.cancelled_quantity += remaining
        db.add(
            _movement(
                tenant_id=reservation.tenant_id,
                stock=stock,
                kind="RELEASE",
                reserved_delta=-remaining,
                reservation_id=reservation.id,
                line_id=line.id,
                actor_id=actor_id,
                reason=reason,
            )
        )

    now = _now()
    sold_any = any(line.completed_quantity > 0 for line in reservation.lines)
    if sold_any:
        # A partly-fulfilled reservation stays a completed sale even when the
        # customer or expiry job releases the rest.
        reservation.status = "COMPLETED"
        reservation.completed_at = now
    else:
        reservation.status = new_status
        reservation.cancelled_at = now
    reservation.updated_at = now
    if reason:
        reservation.cancel_reason = reason
    db.add(
        models.Notification(
            tenant_id=reservation.tenant_id,
            kind="RESERVATION_COMPLETED" if sold_any else f"RESERVATION_{new_status}",
            payload={
                "reservation_id": str(reservation.id),
                "public_ref": reservation.public_ref,
                "reason": reason,
            },
        )
    )


def cancel_reservation(
    db: Session,
    reservation: models.Reservation,
    *,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> models.Reservation:
    locked = db.scalar(
        select(models.Reservation)
        .where(
            models.Reservation.id == reservation.id,
            models.Reservation.tenant_id == reservation.tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise ReservationError("not_found", "Reservation not found.", status_code=404)

    try:
        _release(db, locked, new_status="CANCELLED", reason=reason, actor_id=actor_id)
        db.commit()
        db.refresh(locked)
        return locked
    except Exception:
        db.rollback()
        raise


def complete_reservation(
    db: Session,
    reservation: models.Reservation,
    *,
    line_quantities: list[schemas.CompleteLineIn] | None = None,
    actor_id: uuid.UUID | None = None,
) -> models.Reservation:
    locked = db.scalar(
        select(models.Reservation)
        .where(
            models.Reservation.id == reservation.id,
            models.Reservation.tenant_id == reservation.tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise ReservationError("not_found", "Reservation not found.", status_code=404)
    if locked.status not in ACTIVE_STATUSES:
        raise ReservationError("invalid_state", "Only active reservations can be completed.", status_code=409)

    requested: dict[uuid.UUID, schemas.CompleteLineIn] = {}
    for submitted in line_quantities or []:
        if submitted.line_id in requested:
            raise ReservationError("duplicate_line", "A line was submitted twice.", status_code=400)
        requested[submitted.line_id] = submitted

    line_by_id = {row.id: row for row in locked.lines}
    unknown = set(requested) - set(line_by_id)
    if unknown:
        raise ReservationError("unknown_line", "A line does not belong to this reservation.", status_code=400)

    plan: list[tuple[models.ReservationLine, int, int]] = []
    for res_line in locked.lines:
        remaining = res_line.remaining
        if remaining <= 0:
            continue
        if res_line.id in requested:
            item = requested[res_line.id]
            complete_q = item.complete_quantity
            cancel_q = item.cancel_quantity
            if complete_q + cancel_q > remaining:
                raise ReservationError(
                    "quantity_exceeds_remaining",
                    "Completed plus cancelled quantity exceeds the reserved quantity.",
                    status_code=400,
                )
        else:
            complete_q = remaining
            cancel_q = 0
        if complete_q or cancel_q:
            plan.append((res_line, complete_q, cancel_q))

    if not plan:
        raise ReservationError("nothing_to_do", "No quantities were supplied.", status_code=400)

    stocks = _lock_stocks(db, locked.tenant_id, {res_line.stock_id for res_line, _, _ in plan})
    now = _now()

    try:
        for res_line, complete_q, cancel_q in plan:
            stock = stocks[res_line.stock_id]

            if complete_q:
                if stock.quantity < complete_q or stock.reserved < complete_q:
                    raise ReservationError(
                        "stock_inconsistency",
                        f"Not enough stock to complete '{res_line.name}'.",
                        status_code=409,
                    )
                stock.quantity -= complete_q
                stock.reserved -= complete_q
                res_line.completed_quantity += complete_q
                db.add(
                    _movement(
                        tenant_id=locked.tenant_id,
                        stock=stock,
                        kind="SELL",
                        on_hand_delta=-complete_q,
                        reserved_delta=-complete_q,
                        reservation_id=locked.id,
                        line_id=res_line.id,
                        actor_id=actor_id,
                        reason="reservation completed",
                    )
                )

            if cancel_q:
                if stock.reserved < cancel_q:
                    raise ReservationError(
                        "stock_inconsistency",
                        f"Not enough reserved stock to release '{res_line.name}'.",
                        status_code=409,
                    )
                stock.reserved -= cancel_q
                res_line.cancelled_quantity += cancel_q
                db.add(
                    _movement(
                        tenant_id=locked.tenant_id,
                        stock=stock,
                        kind="RELEASE",
                        reserved_delta=-cancel_q,
                        reservation_id=locked.id,
                        line_id=res_line.id,
                        actor_id=actor_id,
                        reason="line cancelled",
                    )
                )

            stock.updated_at = now

        resolved = all(line.completed_quantity + line.cancelled_quantity == line.quantity for line in locked.lines)
        if resolved:
            sold_any = any(line.completed_quantity > 0 for line in locked.lines)
            locked.status = "COMPLETED" if sold_any else "CANCELLED"
            locked.completed_at = now if sold_any else None
            locked.cancelled_at = None if sold_any else now
        locked.updated_at = now
        db.add(
            models.Notification(
                tenant_id=locked.tenant_id,
                kind="RESERVATION_COMPLETED" if locked.status == "COMPLETED" else "RESERVATION_UPDATED",
                payload={"reservation_id": str(locked.id), "public_ref": locked.public_ref},
            )
        )

        db.commit()
        db.refresh(locked)
        return locked

    except Exception:
        db.rollback()
        raise


def expire_due_reservations(db: Session, now: datetime | None = None) -> int:
    now = now or _now()
    # The worker normally gets a fresh session; expiring here also makes the
    # function safe to call from long-lived sessions and tests.
    db.expire_all()

    tenants = list(db.scalars(select(models.Tenant)).all())
    expired = 0
    for tenant in tenants:
        # RLS is transaction-scoped, so the worker must enter each tenant
        # context before touching tenant-owned tables.
        set_tenant_context(db, tenant.id)
        stmt = (
            select(models.Reservation)
            .where(
                models.Reservation.tenant_id == tenant.id,
                models.Reservation.status.in_(ACTIVE_STATUSES),
                models.Reservation.expires_at <= now,
            )
            .order_by(models.Reservation.expires_at)
            .with_for_update(skip_locked=True)
        )
        due = list(db.scalars(stmt).all())
        for reservation in due:
            try:
                _release(db, reservation, new_status="EXPIRED", reason="hold expired", actor_id=None)
                db.commit()
                expired += 1
            except Exception:
                db.rollback()
                raise
    return expired


def recompute_reserved(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """Return stocks where the stored reserved count differs from the ledger."""

    active = (
        select(
            models.ReservationLine.stock_id,
            func.sum(
                models.ReservationLine.quantity
                - models.ReservationLine.completed_quantity
                - models.ReservationLine.cancelled_quantity
            ).label("active"),
        )
        .join(models.Reservation, models.Reservation.id == models.ReservationLine.reservation_id)
        .where(
            models.Reservation.tenant_id == tenant_id,
            models.Reservation.status.in_(ACTIVE_STATUSES),
        )
        .group_by(models.ReservationLine.stock_id)
        .subquery()
    )

    mismatches: list[dict] = []
    stocks = db.scalars(select(models.Stock).where(models.Stock.tenant_id == tenant_id)).all()
    for stock in stocks:
        expected = db.scalar(select(active.c.active).where(active.c.stock_id == stock.id)) or 0
        expected = int(expected)
        if stock.reserved != expected:
            mismatches.append({"stock_id": str(stock.id), "stored": stock.reserved, "expected": expected})
            stock.reserved = expected
    if mismatches:
        db.commit()
    return mismatches
