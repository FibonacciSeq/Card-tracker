"""Staff/owner API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app import models, schemas, serializers
from app.config import settings
from app.db import get_db, set_tenant_context
from app.deps import get_current_staff, require_owner
from app.security import create_access_token, verify_password
from app.services import reservations as reservation_service

router = APIRouter(prefix="/v1/staff", tags=["staff"])


def _now() -> datetime:
    return datetime.now(UTC)


def _day_start(timezone_name: str) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = datetime.now(tz)
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _staff_tenant(account: models.User) -> uuid.UUID:
    if account.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Staff account has no shop")
    return account.tenant_id


def _tenant(db: Session, account: models.User) -> models.Tenant:
    tenant = db.get(models.Tenant, _staff_tenant(account))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    return tenant


@router.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.StaffLoginIn, db: Session = Depends(get_db)):
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == payload.tenant_slug))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    set_tenant_context(db, tenant.id)
    user = db.scalar(
        select(models.User).where(
            models.User.tenant_id == tenant.id,
            func.lower(models.User.email) == str(payload.email).lower(),
            models.User.role.in_(("owner", "staff")),
        )
    )
    if user is None or not user.password_hash or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(user.id, tenant.id, user.role)
    return schemas.TokenOut(access_token=token, expires_in=settings.access_token_minutes * 60)


@router.get("/me", response_model=schemas.StaffMeOut)
def me(user: models.User = Depends(get_current_staff)):
    return schemas.StaffMeOut(
        id=user.id,
        tenant_id=_staff_tenant(user),
        email=user.email,
        role=user.role,
        display_name=user.display_name,
    )


@router.get("/cards", response_model=list[schemas.CardOut])
def search_cards(
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stmt = select(models.Card).order_by(func.lower(models.Card.name)).limit(limit)
    if query:
        needle = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(models.Card.name).like(needle),
                func.lower(models.Card.set_name).like(needle),
                func.lower(models.Card.collector_number).like(needle),
            )
        )
    return [serializers.card_out(card) for card in db.scalars(stmt).all()]


def _sold_30d(db: Session, tenant_id: uuid.UUID) -> dict[uuid.UUID, int]:
    since = _now() - timedelta(days=30)
    rows = db.execute(
        select(
            models.StockMovement.stock_id,
            func.coalesce(func.sum(-models.StockMovement.on_hand_delta), 0),
        )
        .where(
            models.StockMovement.tenant_id == tenant_id,
            models.StockMovement.kind.in_(("SELL", "SALE")),
            models.StockMovement.created_at >= since,
        )
        .group_by(models.StockMovement.stock_id)
    ).all()
    return {stock_id: int(total) for stock_id, total in rows}


@router.get("/stock", response_model=schemas.StaffStockListOut)
def list_stock(
    query: str | None = Query(default=None, max_length=200),
    only_online: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.Stock)
        .join(models.Card, models.Card.id == models.Stock.card_id)
        .options(joinedload(models.Stock.card))
        .where(models.Stock.tenant_id == _staff_tenant(user))
        .order_by(func.lower(models.Card.name), models.Stock.id)
        .limit(limit)
    )
    if query:
        needle = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(models.Card.name).like(needle),
                func.lower(models.Card.set_name).like(needle),
                func.lower(models.Card.collector_number).like(needle),
            )
        )
    if only_online:
        stmt = stmt.where(models.Stock.is_online.is_(True))

    sold = _sold_30d(db, _staff_tenant(user))
    items = [serializers.staff_stock_out(stock, sold.get(stock.id, 0)) for stock in db.scalars(stmt).all()]
    return schemas.StaffStockListOut(items=items)


def _get_stock(db: Session, tenant_id: uuid.UUID, stock_id: uuid.UUID) -> models.Stock:
    stock = db.scalar(
        select(models.Stock).where(
            models.Stock.id == stock_id,
            models.Stock.tenant_id == tenant_id,
        )
    )
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item not found")
    return stock


@router.post("/stock", response_model=schemas.StaffStockOut, status_code=status.HTTP_201_CREATED)
def create_stock(
    payload: schemas.StockCreateIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    card = db.get(models.Card, payload.card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    tenant = _tenant(db, user)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")

    stock = models.Stock(
        tenant_id=_staff_tenant(user),
        card_id=card.id,
        finish=payload.finish,
        condition=payload.condition,
        language=payload.language.strip().lower() or "en",
        quantity=payload.quantity,
        price_minor=payload.price_minor,
        currency=payload.currency or tenant.currency,
        is_online=payload.is_online,
    )
    db.add(stock)
    try:
        db.flush()
        if payload.quantity:
            db.add(
                models.StockMovement(
                    tenant_id=_staff_tenant(user),
                    stock_id=stock.id,
                    kind="IMPORT",
                    on_hand_delta=payload.quantity,
                    reserved_delta=0,
                    on_hand_after=stock.quantity,
                    reserved_after=stock.reserved,
                    actor_id=user.id,
                    reason="initial stock",
                )
            )
        db.commit()
        db.refresh(stock)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A stock row for this card and variant already exists",
        ) from exc
    return serializers.staff_stock_out(stock)


@router.patch("/stock/{stock_id}", response_model=schemas.StaffStockOut)
def update_stock(
    stock_id: uuid.UUID,
    payload: schemas.StockUpdateIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stock = _get_stock(db, _staff_tenant(user), stock_id)

    if payload.quantity is not None and payload.quantity < stock.reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Quantity cannot be below the {stock.reserved} reserved copies",
        )

    delta = 0
    if payload.quantity is not None:
        delta = payload.quantity - stock.quantity
        stock.quantity = payload.quantity
    if payload.price_minor is not None:
        stock.price_minor = payload.price_minor
    if payload.is_online is not None:
        stock.is_online = payload.is_online
    stock.updated_at = _now()

    if delta:
        db.add(
            models.StockMovement(
                tenant_id=_staff_tenant(user),
                stock_id=stock.id,
                kind="ADJUST",
                on_hand_delta=delta,
                reserved_delta=0,
                on_hand_after=stock.quantity,
                reserved_after=stock.reserved,
                actor_id=user.id,
                reason="stock update",
            )
        )
    db.commit()
    db.refresh(stock)
    return serializers.staff_stock_out(stock)


@router.post("/stock/{stock_id}/adjust", response_model=schemas.StaffStockOut)
def adjust_stock(
    stock_id: uuid.UUID,
    payload: schemas.StockAdjustIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stock = _get_stock(db, _staff_tenant(user), stock_id)
    new_quantity = stock.quantity + payload.delta
    if new_quantity < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity cannot be negative")
    if new_quantity < stock.reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Quantity cannot be below the {stock.reserved} reserved copies",
        )

    stock.quantity = new_quantity
    stock.updated_at = _now()
    db.add(
        models.StockMovement(
            tenant_id=_staff_tenant(user),
            stock_id=stock.id,
            kind="ADJUST",
            on_hand_delta=payload.delta,
            reserved_delta=0,
            on_hand_after=stock.quantity,
            reserved_after=stock.reserved,
            actor_id=user.id,
            reason=payload.reason,
        )
    )
    db.commit()
    db.refresh(stock)
    return serializers.staff_stock_out(stock)


@router.post("/stock/{stock_id}/sell", response_model=schemas.StaffStockOut)
def sell_stock(
    stock_id: uuid.UUID,
    payload: schemas.StockSellIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stock = _get_stock(db, _staff_tenant(user), stock_id)
    if stock.quantity - payload.quantity < stock.reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This sale would consume stock reserved for a customer",
        )

    stock.quantity -= payload.quantity
    stock.updated_at = _now()
    db.add(
        models.StockMovement(
            tenant_id=_staff_tenant(user),
            stock_id=stock.id,
            kind="SALE",
            on_hand_delta=-payload.quantity,
            reserved_delta=0,
            on_hand_after=stock.quantity,
            reserved_after=stock.reserved,
            actor_id=user.id,
            reason=payload.reason,
        )
    )
    db.commit()
    db.refresh(stock)
    return serializers.staff_stock_out(stock)


@router.get("/reservations", response_model=list[schemas.ReservationSummaryOut])
def list_reservations(
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=300),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.Reservation)
        .options(selectinload(models.Reservation.lines))
        .where(models.Reservation.tenant_id == _staff_tenant(user))
        .order_by(models.Reservation.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(models.Reservation.status == status_filter.upper())
    if query:
        needle = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(models.Reservation.customer_name).like(needle),
                func.lower(models.Reservation.public_ref).like(needle),
                func.lower(models.Reservation.email).like(needle),
            )
        )
    return [serializers.reservation_summary_out(res) for res in db.scalars(stmt).all()]


@router.get("/reservations/{reservation_id}", response_model=schemas.StaffReservationOut)
def get_reservation(
    reservation_id: uuid.UUID,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    reservation = db.scalar(
        select(models.Reservation).where(
            models.Reservation.id == reservation_id,
            models.Reservation.tenant_id == _staff_tenant(user),
        )
    )
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    tenant = _tenant(db, user)
    return serializers.staff_reservation_out(reservation, tenant)


@router.post("/reservations/{reservation_id}/status", response_model=schemas.StaffReservationOut)
def update_reservation_status(
    reservation_id: uuid.UUID,
    payload: schemas.StatusUpdateIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    reservation = db.scalar(
        select(models.Reservation).where(
            models.Reservation.id == reservation_id,
            models.Reservation.tenant_id == _staff_tenant(user),
        )
    )
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    if payload.status == "CANCELLED":
        reservation = reservation_service.cancel_reservation(
            db, reservation, reason=payload.reason or "cancelled by staff", actor_id=user.id
        )
    else:
        allowed = {
            "REQUESTED": {"CONFIRMED"},
            "CONFIRMED": {"READY"},
            "READY": set(),
        }
        if payload.status not in allowed.get(reservation.status, set()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot change {reservation.status} to {payload.status}",
            )
        reservation.status = payload.status
        reservation.updated_at = _now()
        db.add(
            models.Notification(
                tenant_id=_staff_tenant(user),
                kind=f"RESERVATION_{payload.status}",
                payload={"reservation_id": str(reservation.id), "public_ref": reservation.public_ref},
            )
        )
        db.commit()
        db.refresh(reservation)

    tenant = _tenant(db, user)
    return serializers.staff_reservation_out(reservation, tenant)


@router.post("/reservations/{reservation_id}/complete", response_model=schemas.StaffReservationOut)
def complete_reservation(
    reservation_id: uuid.UUID,
    payload: schemas.CompleteIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    reservation = db.scalar(
        select(models.Reservation).where(
            models.Reservation.id == reservation_id,
            models.Reservation.tenant_id == _staff_tenant(user),
        )
    )
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    reservation = reservation_service.complete_reservation(
        db, reservation, line_quantities=payload.lines, actor_id=user.id
    )
    tenant = _tenant(db, user)
    return serializers.staff_reservation_out(reservation, tenant)


@router.get("/dashboard", response_model=schemas.DashboardOut)
def dashboard(
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    now = _now()
    today_start = _day_start(tenant.timezone)

    pending = db.scalar(
        select(func.count())
        .select_from(models.Reservation)
        .where(
            models.Reservation.tenant_id == _staff_tenant(user),
            models.Reservation.status == "REQUESTED",
        )
    )
    active = db.scalar(
        select(func.count())
        .select_from(models.Reservation)
        .where(
            models.Reservation.tenant_id == _staff_tenant(user),
            models.Reservation.status.in_(reservation_service.ACTIVE_STATUSES),
        )
    )
    today_sales = db.scalar(
        select(func.coalesce(func.sum(-models.StockMovement.on_hand_delta), 0)).where(
            models.StockMovement.tenant_id == _staff_tenant(user),
            models.StockMovement.kind.in_(("SELL", "SALE")),
            models.StockMovement.created_at >= today_start,
        )
    )
    low_stock = db.scalar(
        select(func.count())
        .select_from(models.Stock)
        .where(
            models.Stock.tenant_id == _staff_tenant(user),
            models.Stock.is_online.is_(True),
            (models.Stock.quantity - models.Stock.reserved) <= 2,
        )
    )
    stale = db.scalar(
        select(func.count())
        .select_from(models.Stock)
        .where(
            models.Stock.tenant_id == _staff_tenant(user),
            models.Stock.is_online.is_(True),
            models.Stock.updated_at < now - timedelta(days=7),
        )
    )

    return schemas.DashboardOut(
        pending_reservations=int(pending or 0),
        active_reservations=int(active or 0),
        today_sales_minor=int(today_sales or 0),
        currency=tenant.currency if tenant else "EUR",
        low_stock=int(low_stock or 0),
        stale_stock=int(stale or 0),
    )


@router.get("/settings", response_model=schemas.StaffShopOut)
def get_settings(
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    return serializers.staff_shop_out(tenant)


@router.patch("/settings", response_model=schemas.StaffShopOut)
def update_settings(
    payload: schemas.SettingsUpdateIn,
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    settings_row = tenant.settings
    if settings_row is None:
        settings_row = models.TenantSettings(tenant_id=tenant.id)
        db.add(settings_row)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings_row, field, value)
    db.commit()
    db.refresh(tenant)
    return serializers.staff_shop_out(tenant)
