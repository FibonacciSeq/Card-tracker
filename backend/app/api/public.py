"""Public storefront endpoints used by the mobile app."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import Session, joinedload

from app import models, schemas, serializers
from app.db import get_db
from app.deps import get_tenant_by_slug
from app.security import hash_guest_token
from app.services import reservations as reservation_service

router = APIRouter(prefix="/v1", tags=["public"])


def _encode_cursor(name: str, stock_id: uuid.UUID) -> str:
    raw = json.dumps({"n": name.lower(), "i": str(stock_id)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(raw)
        return str(data["n"]).lower(), uuid.UUID(data["i"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from exc


@router.get("/shops", response_model=list[schemas.ShopOut])
def list_shops(
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.Tenant)
        .join(models.TenantSettings, models.TenantSettings.tenant_id == models.Tenant.id)
        .options(joinedload(models.Tenant.settings))
        .where(
            models.Tenant.status.in_(("active", "trialing")),
            models.TenantSettings.directory_opt_in.is_(True),
        )
        .order_by(func.lower(models.Tenant.name))
        .limit(limit)
    )
    if query:
        needle = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(models.Tenant.name).like(needle),
                func.lower(models.Tenant.slug).like(needle),
            )
        )
    tenants = db.scalars(stmt).all()
    return [serializers.shop_out(tenant) for tenant in tenants]


@router.get("/shops/{slug}", response_model=schemas.ShopOut)
def get_shop(slug: str, db: Session = Depends(get_db)):
    tenant = get_tenant_by_slug(slug, db)
    return serializers.shop_out(tenant)


@router.get("/shops/{slug}/stock", response_model=schemas.StockListOut)
def list_stock(
    slug: str,
    query: str | None = Query(default=None, max_length=200),
    set_code: str | None = Query(default=None, max_length=20),
    rarity: str | None = Query(default=None, max_length=40),
    finish: str | None = Query(default=None, max_length=20),
    condition: str | None = Query(default=None, max_length=10),
    language: str | None = Query(default=None, max_length=10),
    min_price_minor: int | None = Query(default=None, ge=0),
    max_price_minor: int | None = Query(default=None, ge=0),
    available_only: bool = Query(default=False),
    sort: str = Query(default="relevance", pattern="^(relevance|name|price_asc|price_desc|newest)$"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    tenant = get_tenant_by_slug(slug, db)

    stmt = (
        select(models.Stock, models.Card)
        .join(models.Card, models.Card.id == models.Stock.card_id)
        .where(
            models.Stock.tenant_id == tenant.id,
            models.Stock.is_online.is_(True),
        )
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
    if set_code:
        stmt = stmt.where(func.lower(models.Card.set_code) == set_code.lower())
    if rarity:
        stmt = stmt.where(func.lower(models.Card.rarity) == rarity.lower())
    if finish:
        stmt = stmt.where(models.Stock.finish == finish)
    if condition:
        stmt = stmt.where(models.Stock.condition == condition)
    if language:
        stmt = stmt.where(models.Stock.language == language)
    if min_price_minor is not None:
        stmt = stmt.where(models.Stock.price_minor >= min_price_minor)
    if max_price_minor is not None:
        stmt = stmt.where(models.Stock.price_minor <= max_price_minor)
    if available_only:
        stmt = stmt.where(models.Stock.quantity > models.Stock.reserved)

    if sort == "price_asc":
        stmt = stmt.order_by(models.Stock.price_minor, models.Stock.id)
    elif sort == "price_desc":
        stmt = stmt.order_by(models.Stock.price_minor.desc(), models.Stock.id)
    elif sort == "newest":
        stmt = stmt.order_by(models.Stock.created_at.desc(), models.Stock.id)
    elif sort == "name" or sort == "relevance":
        stmt = stmt.order_by(func.lower(models.Card.name), models.Stock.id)
        if cursor:
            name, stock_id = _decode_cursor(cursor)
            stmt = stmt.where(tuple_(func.lower(models.Card.name), models.Stock.id) > (name, stock_id))

    if sort in ("price_asc", "price_desc", "newest") and cursor:
        last_id = uuid.UUID(cursor) if sort == "newest" else None
        if last_id is not None:
            stmt = stmt.where(models.Stock.id > last_id)

    rows = db.execute(stmt.limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [serializers.stock_item_out(stock, card) for stock, card in rows]
    next_cursor = None
    if has_more and rows:
        last_stock = rows[-1][0]
        if sort in ("name", "relevance"):
            next_cursor = _encode_cursor(rows[-1][1].name, last_stock.id)
        else:
            next_cursor = str(last_stock.id)

    return schemas.StockListOut(items=items, next_cursor=next_cursor)


@router.get("/shops/{slug}/stock/{stock_id}", response_model=schemas.StockItemOut)
def get_stock_item(slug: str, stock_id: uuid.UUID, db: Session = Depends(get_db)):
    tenant = get_tenant_by_slug(slug, db)
    stock = db.scalar(
        select(models.Stock).where(
            models.Stock.id == stock_id,
            models.Stock.tenant_id == tenant.id,
            models.Stock.is_online.is_(True),
        )
    )
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item not found")
    return serializers.stock_item_out(stock)


@router.get("/shops/{slug}/facets")
def stock_facets(slug: str, db: Session = Depends(get_db)):
    tenant = get_tenant_by_slug(slug, db)
    base = (
        select(models.Card, models.Stock)
        .join(models.Stock, models.Stock.card_id == models.Card.id)
        .where(models.Stock.tenant_id == tenant.id, models.Stock.is_online.is_(True))
        .subquery()
    )

    def group(column):
        rows = db.execute(
            select(column, func.count()).select_from(base).group_by(column).order_by(func.count().desc())
        ).all()
        return [{"value": value, "count": count} for value, count in rows if value]

    return {
        "sets": group(base.c.set_code),
        "rarities": group(base.c.rarity),
        "finishes": group(base.c.finish),
        "conditions": group(base.c.condition),
        "languages": group(base.c.language),
    }


@router.post(
    "/shops/{slug}/reservations",
    response_model=schemas.ReservationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    slug: str,
    payload: schemas.ReservationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    tenant = get_tenant_by_slug(slug, db)
    reservation, access_token = reservation_service.create_reservation(
        db, tenant, payload, idempotency_key=idempotency_key
    )
    return serializers.reservation_out(reservation, tenant, access_token=access_token)


def _reservation_or_403(
    db: Session,
    tenant: models.Tenant,
    reservation_id: uuid.UUID,
    token: str | None,
) -> models.Reservation:
    reservation = db.scalar(
        select(models.Reservation).where(
            models.Reservation.id == reservation_id,
            models.Reservation.tenant_id == tenant.id,
        )
    )
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if not token or reservation.access_token_hash != hash_guest_token(token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid reservation token")
    return reservation


@router.get("/reservations/{reservation_id}", response_model=schemas.ReservationOut)
def get_reservation(
    reservation_id: uuid.UUID,
    shop_slug: str = Header(alias="X-Shop-Slug"),
    token: str | None = Header(default=None, alias="X-Reservation-Token"),
    db: Session = Depends(get_db),
):
    tenant = get_tenant_by_slug(shop_slug, db)
    reservation = _reservation_or_403(db, tenant, reservation_id, token)
    return serializers.reservation_out(reservation, tenant)


@router.post("/reservations/{reservation_id}/cancel", response_model=schemas.ReservationOut)
def cancel_reservation(
    reservation_id: uuid.UUID,
    shop_slug: str = Header(alias="X-Shop-Slug"),
    token: str | None = Header(default=None, alias="X-Reservation-Token"),
    db: Session = Depends(get_db),
):
    tenant = get_tenant_by_slug(shop_slug, db)
    reservation = _reservation_or_403(db, tenant, reservation_id, token)
    reservation = reservation_service.cancel_reservation(db, reservation, reason="cancelled by customer", actor_id=None)
    return serializers.reservation_out(reservation, tenant)


@router.get("/shops/{slug}/reservations/{public_ref}", response_model=schemas.ReservationOut)
def get_reservation_by_ref(
    slug: str,
    public_ref: str,
    token: str | None = Header(default=None, alias="X-Reservation-Token"),
    db: Session = Depends(get_db),
):
    tenant = get_tenant_by_slug(slug, db)
    reservation = db.scalar(
        select(models.Reservation).where(
            models.Reservation.tenant_id == tenant.id,
            models.Reservation.public_ref == public_ref.upper(),
        )
    )
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if not token or reservation.access_token_hash != hash_guest_token(token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid reservation token")
    return serializers.reservation_out(reservation, tenant)


@router.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
