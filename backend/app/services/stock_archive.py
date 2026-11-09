"""Permanent deletion of archived stock.

Archiving is reversible. Permanent deletion is not, so the rules live in one
place: only archived rows are eligible, and a row with an active customer hold
is always kept. Reservation history is preserved by detaching its line rows
from the stock row instead of deleting the reservation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.orm import Session

from app import models
from app.db import set_tenant_context
from app.services import audit, reservations

_DELETE_CHUNK = 500


@dataclass(frozen=True)
class ArchiveDeleteResult:
    deleted: int
    kept: int


def _active_hold_exists() -> ColumnElement[bool]:
    """True when an open reservation still expects this stock row."""
    return (
        select(models.ReservationLine.id)
        .join(models.Reservation, models.Reservation.id == models.ReservationLine.reservation_id)
        .where(
            models.ReservationLine.stock_id == models.Stock.id,
            models.Reservation.tenant_id == models.Stock.tenant_id,
            models.Reservation.status.in_(reservations.ACTIVE_STATUSES),
            models.ReservationLine.quantity
            - models.ReservationLine.completed_quantity
            - models.ReservationLine.cancelled_quantity
            > 0,
        )
        .exists()
    )


def _archived_scope(
    tenant_id: uuid.UUID,
    *,
    cutoff: datetime | None = None,
    stock_id: uuid.UUID | None = None,
):
    stmt = select(models.Stock.id).where(
        models.Stock.tenant_id == tenant_id,
        models.Stock.archived_at.is_not(None),
    )
    if stock_id is not None:
        stmt = stmt.where(models.Stock.id == stock_id)
    if cutoff is not None:
        stmt = stmt.where(models.Stock.archived_at <= cutoff)
    return stmt


def _archived_count(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    cutoff: datetime | None = None,
    stock_id: uuid.UUID | None = None,
) -> int:
    scope = _archived_scope(tenant_id, cutoff=cutoff, stock_id=stock_id).subquery()
    return int(db.scalar(select(func.count()).select_from(scope)) or 0)


def deletable_archived_ids(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    cutoff: datetime | None = None,
    stock_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    stmt = _archived_scope(tenant_id, cutoff=cutoff, stock_id=stock_id).where(
        models.Stock.reserved == 0,
        ~_active_hold_exists(),
    )
    return list(db.scalars(stmt).all())


def stock_has_active_hold(db: Session, stock: models.Stock) -> bool:
    if stock.reserved > 0:
        return True
    statement = (
        select(models.ReservationLine.id)
        .join(models.Reservation, models.Reservation.id == models.ReservationLine.reservation_id)
        .where(
            models.ReservationLine.stock_id == stock.id,
            models.Reservation.tenant_id == stock.tenant_id,
            models.Reservation.status.in_(reservations.ACTIVE_STATUSES),
            models.ReservationLine.quantity
            - models.ReservationLine.completed_quantity
            - models.ReservationLine.cancelled_quantity
            > 0,
        )
        .limit(1)
    )
    return db.scalar(statement) is not None


def delete_archived_stock(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    cutoff: datetime | None = None,
    stock_id: uuid.UUID | None = None,
) -> ArchiveDeleteResult:
    """Delete eligible archived rows and report how many were kept by holds.

    The caller owns the transaction and commits. Reservation lines are detached
    first so the customer's line history survives even on databases where the
    foreign key is not enforced.
    """
    ids = deletable_archived_ids(db, tenant_id, cutoff=cutoff, stock_id=stock_id)
    total = _archived_count(db, tenant_id, cutoff=cutoff, stock_id=stock_id)
    if not ids:
        return ArchiveDeleteResult(deleted=0, kept=total)

    # Keep each statement below SQLite's variable limit so deleting a very
    # large archive works the same as deleting a handful of rows.
    for start in range(0, len(ids), _DELETE_CHUNK):
        chunk = ids[start : start + _DELETE_CHUNK]
        db.execute(
            update(models.ReservationLine).where(models.ReservationLine.stock_id.in_(chunk)).values(stock_id=None)
        )
        db.execute(
            delete(models.Stock).where(
                models.Stock.id.in_(chunk),
                models.Stock.tenant_id == tenant_id,
                models.Stock.archived_at.is_not(None),
            )
        )
    return ArchiveDeleteResult(deleted=len(ids), kept=max(0, total - len(ids)))


def purge_expired_archived_stock(
    db: Session,
    now: datetime | None = None,
    *,
    tenant_id: uuid.UUID | None = None,
) -> int:
    """Delete archived rows older than each shop's retention setting.

    A setting of ``0`` keeps archived stock forever. Holds are still honoured.
    Commits per shop so the worker's RLS tenant context stays isolated.
    """
    current = now or datetime.now(UTC)
    tenant_ids = [tenant_id] if tenant_id is not None else list(db.scalars(select(models.Tenant.id)).all())
    deleted_total = 0
    for current_tenant in tenant_ids:
        set_tenant_context(db, current_tenant)
        settings_row = db.get(models.TenantSettings, current_tenant)
        retention_days = settings_row.archive_retention_days if settings_row is not None else 0
        if retention_days <= 0:
            continue
        cutoff = current - timedelta(days=retention_days)
        result = delete_archived_stock(db, current_tenant, cutoff=cutoff)
        if result.deleted:
            audit.record(
                db,
                tenant_id=current_tenant,
                actor_id=None,
                action="stock.delete_expired",
                entity_type="stock",
                entity_id="batch",
                summary=(
                    f"Deleted {result.deleted} archived stock row"
                    f"{'' if result.deleted == 1 else 's'} past the retention period"
                ),
                data={"deleted": result.deleted, "kept": result.kept, "retention_days": retention_days},
            )
            deleted_total += result.deleted
        db.commit()
    return deleted_total
