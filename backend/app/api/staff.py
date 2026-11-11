"""Staff/owner API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app import models, schemas, serializers
from app.config import settings
from app.db import get_db, set_tenant_context
from app.deps import get_current_staff, require_owner
from app.security import create_access_token, hash_password, verify_password
from app.services import audit, notifications, ratelimit, restock, scryfall_pricing, stock_archive, stock_csv
from app.services import card_requests as card_request_service
from app.services import exchange_rates as exchange_rate_service
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
def login(payload: schemas.StaffLoginIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.enforce(
        request,
        scope="staff-login",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
        extra=payload.tenant_slug,
    )
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
    if (
        user is None
        or not user.is_active
        or not user.password_hash
        or not verify_password(user.password_hash, payload.password)
    ):
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


def _user_out(row: models.User) -> schemas.StaffUserOut:
    return schemas.StaffUserOut(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        role=row.role,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _get_shop_user(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> models.User:
    row = db.scalar(
        select(models.User).where(
            models.User.id == user_id,
            models.User.tenant_id == tenant_id,
            models.User.role.in_(("owner", "staff")),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    return row


def _active_owner_count(db: Session, tenant_id: uuid.UUID, *, excluding: uuid.UUID | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(models.User)
        .where(
            models.User.tenant_id == tenant_id,
            models.User.role == "owner",
            models.User.is_active.is_(True),
        )
    )
    if excluding is not None:
        stmt = stmt.where(models.User.id != excluding)
    return int(db.scalar(stmt) or 0)


@router.get("/users", response_model=list[schemas.StaffUserOut])
def list_users(
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(models.User)
        .where(
            models.User.tenant_id == _staff_tenant(user),
            models.User.role.in_(("owner", "staff")),
        )
        .order_by(func.lower(models.User.email))
    ).all()
    return [_user_out(row) for row in rows]


@router.post("/users", response_model=schemas.StaffUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.StaffUserCreateIn,
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    tenant_id = _staff_tenant(user)
    row = models.User(
        tenant_id=tenant_id,
        email=str(payload.email).lower(),
        display_name=payload.display_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(row)
    try:
        # Flush first: the UUID default is applied by the database layer, and
        # the audit row needs the real id.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Someone with this email already has an account at this shop",
        ) from exc

    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=user.id,
        action="staff.create",
        entity_type="user",
        entity_id=row.id,
        summary=f"Added {row.email} as {row.role}",
        data={"email": row.email, "role": row.role},
    )
    db.commit()
    db.refresh(row)
    return _user_out(row)


@router.patch("/users/{user_id}", response_model=schemas.StaffUserOut)
def update_user(
    user_id: uuid.UUID,
    payload: schemas.StaffUserUpdateIn,
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    tenant_id = _staff_tenant(user)
    row = _get_shop_user(db, tenant_id, user_id)
    changes = payload.model_dump(exclude_unset=True)

    if row.id == user.id and changes.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    loses_owner = row.role == "owner" and (changes.get("role", "owner") != "owner" or changes.get("is_active") is False)
    if loses_owner and _active_owner_count(db, tenant_id, excluding=row.id) < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A shop needs at least one active owner",
        )

    if "display_name" in changes:
        row.display_name = changes["display_name"]
    if changes.get("password"):
        row.password_hash = hash_password(changes["password"])
    if changes.get("role"):
        row.role = changes["role"]
    if changes.get("is_active") is not None:
        row.is_active = changes["is_active"]

    summary = f"Updated {row.email}"
    if changes.get("password"):
        summary += " (password reset)"
    if row.role != "owner" and changes.get("role") == "staff":
        summary += " (role: staff)"
    elif changes.get("role") == "owner":
        summary += " (role: owner)"
    if changes.get("is_active") is False:
        summary += " (deactivated)"
    elif changes.get("is_active") is True:
        summary += " (reactivated)"

    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=user.id,
        action="staff.update",
        entity_type="user",
        entity_id=row.id,
        summary=summary,
        data={key: ("***" if key == "password" else value) for key, value in changes.items()},
    )
    db.commit()
    db.refresh(row)
    return _user_out(row)


@router.get("/audit", response_model=list[schemas.AuditEventOut])
def list_audit_events(
    action: str | None = Query(default=None, max_length=80),
    entity_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.AuditEvent, models.User.email)
        .outerjoin(models.User, models.User.id == models.AuditEvent.actor_id)
        .where(models.AuditEvent.tenant_id == _staff_tenant(user))
        .order_by(models.AuditEvent.created_at.desc(), models.AuditEvent.id.desc())
        .limit(limit)
    )
    if action:
        stmt = stmt.where(models.AuditEvent.action.like(f"{action}%"))
    if entity_type:
        stmt = stmt.where(models.AuditEvent.entity_type == entity_type)

    return [
        schemas.AuditEventOut(
            id=event.id,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            summary=event.summary,
            actor_id=event.actor_id,
            actor_email=email,
            data=event.data or {},
            created_at=event.created_at,
        )
        for event, email in db.execute(stmt).all()
    ]


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
    archived: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    tenant_id = tenant.id
    if archived:
        retention_days = tenant.settings.archive_retention_days if tenant.settings is not None else 0
        if retention_days > 0:
            # Local development often runs only the API, so expiring archived
            # stock lazily keeps this view consistent without the worker.
            stock_archive.purge_expired_archived_stock(db, tenant_id=tenant_id)

    stmt = (
        select(models.Stock)
        .join(models.Card, models.Card.id == models.Stock.card_id)
        .options(joinedload(models.Stock.card))
        .where(models.Stock.tenant_id == tenant_id)
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
    if archived:
        stmt = stmt.where(models.Stock.archived_at.is_not(None))
    else:
        stmt = stmt.where(models.Stock.archived_at.is_(None))
        if only_online:
            stmt = stmt.where(models.Stock.is_online.is_(True))

    sold = _sold_30d(db, tenant_id)
    waiting_rows = db.execute(
        select(
            models.RestockAlert.card_id,
            models.RestockAlert.finish,
            models.RestockAlert.condition,
            models.RestockAlert.language,
            func.count(),
        )
        .where(
            models.RestockAlert.tenant_id == tenant_id,
            models.RestockAlert.notified_at.is_(None),
        )
        .group_by(
            models.RestockAlert.card_id,
            models.RestockAlert.finish,
            models.RestockAlert.condition,
            models.RestockAlert.language,
        )
    ).all()
    waiting = {
        (card_id, finish, condition, language): int(count)
        for card_id, finish, condition, language, count in waiting_rows
    }
    items = [
        serializers.staff_stock_out(
            stock,
            sold.get(stock.id, 0),
            waiting.get((stock.card_id, stock.finish, stock.condition, stock.language), 0),
        )
        for stock in db.scalars(stmt).all()
    ]
    return schemas.StaffStockListOut(items=items)


MAX_IMPORT_BYTES = 5 * 1024 * 1024


@router.get("/stock/export.csv")
def export_stock_csv(
    archived: bool = Query(default=False),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Download stock in the same shape the importer accepts."""
    tenant = _tenant(db, user)
    body = stock_csv.render_csv(stock_csv.export_rows(db, _staff_tenant(user), archived=archived))
    suffix = "-archived" if archived else ""
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="stock-{tenant.slug}{suffix}.csv"'},
    )


def _stock_import_pricing(tenant: models.Tenant) -> dict[str, int] | None:
    rules = tenant.settings.stock_import_pricing if tenant.settings else None
    fields = ("threshold_minor", "fixed_price_minor", "markup_percent")
    if not isinstance(rules, dict) or not all(type(rules.get(field)) is int for field in fields):
        return None
    return {field: rules[field] for field in fields}


def _stock_import_pricing_out(tenant: models.Tenant) -> schemas.StockImportPricingOut:
    rules = _stock_import_pricing(tenant)
    return schemas.StockImportPricingOut(
        currency=tenant.currency,
        configured=rules is not None,
        threshold_minor=rules.get("threshold_minor") if rules else None,
        fixed_price_minor=rules.get("fixed_price_minor") if rules else None,
        markup_percent=rules.get("markup_percent") if rules else None,
    )


@router.get("/stock/import-pricing", response_model=schemas.StockImportPricingOut)
def get_stock_import_pricing(
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    return _stock_import_pricing_out(_tenant(db, user))


@router.patch("/stock/import-pricing", response_model=schemas.StockImportPricingOut)
def update_stock_import_pricing(
    payload: schemas.StockImportPricingIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    settings_row = tenant.settings
    if settings_row is None:
        settings_row = models.TenantSettings(tenant_id=tenant.id)
        tenant.settings = settings_row
        db.add(settings_row)

    rules = payload.model_dump()
    settings_row.stock_import_pricing = rules
    audit.record(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="stock.import_pricing.update",
        entity_type="shop",
        entity_id=tenant.id,
        summary="Updated shop stock import pricing rules",
        data=rules,
    )
    db.commit()
    db.refresh(tenant)
    return _stock_import_pricing_out(tenant)


@router.post("/stock/import", response_model=schemas.StockImportReportOut)
def import_stock_csv(
    file: UploadFile = File(...),
    dry_run: bool = Form(default=True),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Import a stock CSV. Defaults to a dry run so a bad file changes nothing."""
    tenant = _tenant(db, user)
    raw = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is larger than 5 MB. Split the import into batches.",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded. In Excel, use Save as > CSV UTF-8.",
        ) from exc

    try:
        rows, parse_errors = stock_csv.parse_csv(text, tenant.currency)
    except stock_csv.CsvFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    input_row_count = len(rows) + len(parse_errors)
    scryfall_errors: list[stock_csv.RowError] = []
    pricing = scryfall_pricing.pricing_settings(tenant.settings)
    if pricing is not None:
        try:
            rows, scryfall_errors = scryfall_pricing.price_import_rows(db, tenant, rows, pricing)
        except exchange_rate_service.ExchangeRateError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    exchange_rate_rows: list[schemas.ExchangeRateOut] = []
    purchase_rows = [row for row in rows if row.uses_pricing_rules]
    if purchase_rows:
        pricing = _stock_import_pricing(tenant)
        if pricing is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Set shop stock import pricing rules before checking a ManaBox purchase-price CSV.",
            )
        rates = {}
        try:
            for source_currency in sorted({row.currency.upper() for row in purchase_rows}):
                quote = exchange_rate_service.get_latest_rate(source_currency, tenant.currency)
                rates[source_currency] = quote.rate
                exchange_rate_rows.append(
                    schemas.ExchangeRateOut(
                        source_currency=quote.source_currency,
                        target_currency=quote.target_currency,
                        rate=str(quote.rate),
                        rate_date=quote.rate_date.isoformat(),
                    )
                )
            rows = stock_csv.price_purchase_rows(rows, tenant.currency, rates, pricing)
        except exchange_rate_service.ExchangeRateError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    created, updated, unchanged, apply_errors = stock_csv.apply_rows(db, tenant, user.id, rows, dry_run=dry_run)
    if dry_run:
        db.rollback()
    else:
        if created or updated:
            audit.record(
                db,
                tenant_id=tenant.id,
                actor_id=user.id,
                action="stock.import",
                entity_type="stock",
                entity_id="batch",
                summary=f"Imported stock CSV: {created} new, {updated} updated, {len(parse_errors) + len(apply_errors)} skipped",
                data={"created": created, "updated": updated, "unchanged": unchanged},
            )
        db.commit()

    errors = parse_errors + scryfall_errors + apply_errors
    return schemas.StockImportReportOut(
        dry_run=dry_run,
        rows=input_row_count,
        created=created,
        updated=updated,
        unchanged=unchanged,
        errors=[
            schemas.StockImportErrorOut(row=error.row, message=error.message, field=error.field) for error in errors
        ],
        exchange_rates=exchange_rate_rows,
    )


@router.post("/stock/archive", response_model=schemas.StockArchiveResultOut)
def archive_all_stock(
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Move every active stock row for this shop into the archived view."""
    tenant_id = _staff_tenant(user)
    rows = list(
        db.scalars(
            select(models.Stock).where(
                models.Stock.tenant_id == tenant_id,
                models.Stock.archived_at.is_(None),
            )
        ).all()
    )
    now = _now()
    reserved = 0
    for stock in rows:
        reserved += stock.reserved
        stock.archived_at = now
        stock.updated_at = now
    if rows:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="stock.archive_all",
            entity_type="stock",
            entity_id="batch",
            summary=f"Archived all stock ({len(rows)} rows)",
            data={"archived": len(rows), "reserved": reserved},
        )
    db.commit()
    return schemas.StockArchiveResultOut(archived=len(rows), reserved=reserved)


@router.delete("/stock/archive", response_model=schemas.StockDeleteResultOut)
def delete_archived_stock(
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Permanently delete every archived row that has no active customer hold."""
    tenant_id = _staff_tenant(user)
    result = stock_archive.delete_archived_stock(db, tenant_id)
    if result.deleted:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="stock.delete_all",
            entity_type="stock",
            entity_id="batch",
            summary=f"Permanently deleted archived stock ({result.deleted} rows)",
            data={"deleted": result.deleted, "kept": result.kept},
        )
    db.commit()
    return schemas.StockDeleteResultOut(deleted=result.deleted, kept=result.kept)


@router.delete("/stock/{stock_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_one_archived_stock(
    stock_id: uuid.UUID,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Permanently delete a single archived stock row."""
    tenant_id = _staff_tenant(user)
    stock = db.scalar(
        select(models.Stock)
        .options(joinedload(models.Stock.card))
        .where(
            models.Stock.id == stock_id,
            models.Stock.tenant_id == tenant_id,
        )
    )
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item not found")
    if stock.archived_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only archived stock can be permanently deleted",
        )
    if stock_archive.stock_has_active_hold(db, stock):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This archived card still has customer holds and cannot be deleted yet",
        )

    summary = f"Deleted archived stock: {stock.card.name} ({stock.condition} {stock.finish} {stock.language})"
    result = stock_archive.delete_archived_stock(db, tenant_id, stock_id=stock_id)
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=user.id,
        action="stock.delete",
        entity_type="stock",
        entity_id=stock_id,
        summary=summary,
        data={"deleted": result.deleted, "kept": result.kept},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_stock(
    db: Session,
    tenant_id: uuid.UUID,
    stock_id: uuid.UUID,
    *,
    allow_archived: bool = False,
) -> models.Stock:
    stock = db.scalar(
        select(models.Stock).where(
            models.Stock.id == stock_id,
            models.Stock.tenant_id == tenant_id,
        )
    )
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item not found")
    if stock.archived_at is not None and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived stock must be restored before it can be changed",
        )
    return stock


def _normalize_stock_language(value: str) -> str:
    language = value.strip().lower()
    if not (2 <= len(language) <= 5 and language.isascii() and language.isalpha()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="language must be a 2–5 letter code such as 'en' or 'ja'",
        )
    return language


def _stock_currency(value: str | None, tenant: models.Tenant) -> str:
    currency = (value or tenant.currency).strip().upper()
    if currency != tenant.currency.upper():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Stock currency must match the shop currency ({tenant.currency})",
        )
    return currency


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
    language = _normalize_stock_language(payload.language)
    currency = _stock_currency(payload.currency, tenant)

    existing = db.scalar(
        select(models.Stock).where(
            models.Stock.tenant_id == _staff_tenant(user),
            models.Stock.card_id == card.id,
            models.Stock.finish == payload.finish,
            models.Stock.condition == payload.condition,
            models.Stock.language == language,
            models.Stock.archived_at.is_not(None),
        )
    )
    if existing is not None:
        if payload.quantity < existing.reserved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Quantity cannot be below the {existing.reserved} reserved copies",
            )
        delta = payload.quantity - existing.quantity
        existing.archived_at = None
        existing.quantity = payload.quantity
        existing.price_minor = payload.price_minor
        existing.currency = currency
        existing.is_online = payload.is_online
        existing.updated_at = _now()
        if delta:
            db.add(
                models.StockMovement(
                    tenant_id=_staff_tenant(user),
                    stock_id=existing.id,
                    kind="IMPORT",
                    on_hand_delta=delta,
                    reserved_delta=0,
                    on_hand_after=existing.quantity,
                    reserved_after=existing.reserved,
                    actor_id=user.id,
                    reason="restored archived stock",
                )
            )
        restock.notify_waiting(db, tenant, existing)
        audit.record(
            db,
            tenant_id=_staff_tenant(user),
            actor_id=user.id,
            action="stock.restore",
            entity_type="stock",
            entity_id=existing.id,
            summary=f"Restored {card.name} ({existing.finish}/{existing.condition}) x{existing.quantity}",
            data={
                "card_name": card.name,
                "finish": existing.finish,
                "condition": existing.condition,
                "quantity": existing.quantity,
                "price_minor": existing.price_minor,
            },
        )
        db.commit()
        db.refresh(existing)
        return serializers.staff_stock_out(existing)

    stock = models.Stock(
        tenant_id=_staff_tenant(user),
        card_id=card.id,
        finish=payload.finish,
        condition=payload.condition,
        language=language,
        quantity=payload.quantity,
        price_minor=payload.price_minor,
        currency=currency,
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
        restock.notify_waiting(db, tenant, stock)
        audit.record(
            db,
            tenant_id=_staff_tenant(user),
            actor_id=user.id,
            action="stock.create",
            entity_type="stock",
            entity_id=stock.id,
            summary=f"Added {card.name} ({stock.finish}/{stock.condition}) x{stock.quantity}",
            data={
                "card_name": card.name,
                "finish": stock.finish,
                "condition": stock.condition,
                "quantity": stock.quantity,
                "price_minor": stock.price_minor,
            },
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


@router.post("/stock/{stock_id}/restore", response_model=schemas.StaffStockOut)
def restore_stock(
    stock_id: uuid.UUID,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stock = _get_stock(db, _staff_tenant(user), stock_id, allow_archived=True)
    if stock.archived_at is not None:
        stock.archived_at = None
        stock.updated_at = _now()
        restock.notify_waiting(db, _tenant(db, user), stock)
        audit.record(
            db,
            tenant_id=_staff_tenant(user),
            actor_id=user.id,
            action="stock.restore",
            entity_type="stock",
            entity_id=stock.id,
            summary=f"Restored {stock.card.name} ({stock.finish}/{stock.condition})",
            data={"quantity": stock.quantity, "price_minor": stock.price_minor},
        )
        db.commit()
        db.refresh(stock)
    return serializers.staff_stock_out(stock)


@router.patch("/stock/{stock_id}", response_model=schemas.StaffStockOut)
def update_stock(
    stock_id: uuid.UUID,
    payload: schemas.StockUpdateIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    stock = _get_stock(db, _staff_tenant(user), stock_id)
    was_online = stock.is_online

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
    if delta > 0 or (payload.is_online is True and not was_online):
        restock.notify_waiting(db, _tenant(db, user), stock)
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        audit.record(
            db,
            tenant_id=_staff_tenant(user),
            actor_id=user.id,
            action="stock.update",
            entity_type="stock",
            entity_id=stock.id,
            summary=f"Changed stock for {stock.card.name}",
            data={**changes, "delta": delta},
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
    if payload.delta > 0:
        restock.notify_waiting(db, _tenant(db, user), stock)
    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="stock.adjust",
        entity_type="stock",
        entity_id=stock.id,
        summary=f"Adjusted {stock.card.name} by {payload.delta:+d} ({payload.reason})",
        data={"delta": payload.delta, "on_hand_after": stock.quantity, "reason": payload.reason},
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
    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="stock.sell",
        entity_type="stock",
        entity_id=stock.id,
        summary=f"Sold {payload.quantity} x {stock.card.name} ({payload.reason})",
        data={"quantity": payload.quantity, "on_hand_after": stock.quantity, "reason": payload.reason},
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

    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="reservation.status",
        entity_type="reservation",
        entity_id=reservation.id,
        summary=f"Reservation {reservation.public_ref}: {reservation.status} -> {payload.status}",
        data={"from": reservation.status, "to": payload.status, "reason": payload.reason},
    )
    if payload.status == "CANCELLED":
        reservation = reservation_service.cancel_reservation(
            db, reservation, reason=payload.reason or "cancelled by staff", actor_id=user.id
        )
        db.commit()
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
        notifications.enqueue(
            db,
            _staff_tenant(user),
            f"RESERVATION_{payload.status}",
            {
                "reservation_id": str(reservation.id),
                "public_ref": reservation.public_ref,
                "status": payload.status,
                "customer_name": reservation.customer_name,
                "expires_at": reservation.expires_at.isoformat(),
            },
            recipient=reservation.email,
            user_id=reservation.customer_id,
            push=True,
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

    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="reservation.complete",
        entity_type="reservation",
        entity_id=reservation.id,
        summary=f"Completed reservation {reservation.public_ref}",
        data={"lines": [line.model_dump(mode="json") for line in payload.lines] if payload.lines else None},
    )
    reservation = reservation_service.complete_reservation(
        db, reservation, line_quantities=payload.lines, actor_id=user.id
    )
    tenant = _tenant(db, user)
    return serializers.staff_reservation_out(reservation, tenant)


def _get_card_request(db: Session, tenant_id: uuid.UUID, request_id: uuid.UUID) -> models.CardRequest:
    row = db.scalar(
        select(models.CardRequest)
        .options(joinedload(models.CardRequest.reservation))
        .where(
            models.CardRequest.id == request_id,
            models.CardRequest.tenant_id == tenant_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return row


@router.get("/card-requests", response_model=list[schemas.StaffCardRequestOut])
def list_card_requests(
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=200, ge=1, le=500),
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    stmt = (
        select(models.CardRequest)
        .options(joinedload(models.CardRequest.reservation))
        .where(models.CardRequest.tenant_id == _staff_tenant(user))
        .order_by(models.CardRequest.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(models.CardRequest.status == status_filter.upper())
    return [serializers.staff_card_request_out(row, tenant) for row in db.scalars(stmt).all()]


@router.post("/card-requests/{request_id}/quote", response_model=schemas.StaffCardRequestOut)
def quote_card_request(
    request_id: uuid.UUID,
    payload: schemas.QuoteIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    row = _get_card_request(db, _staff_tenant(user), request_id)
    row = card_request_service.quote(db, tenant, row, payload)
    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="card_request.quote",
        entity_type="card_request",
        entity_id=row.id,
        summary=f"Quoted {row.public_ref} at {row.quote_price_minor} {row.quote_currency}",
        data={
            "quote_price_minor": row.quote_price_minor,
            "quote_expires_at": row.quote_expires_at.isoformat() if row.quote_expires_at else None,
        },
    )
    db.commit()
    return serializers.staff_card_request_out(row, tenant)


@router.post("/card-requests/{request_id}/decline", response_model=schemas.StaffCardRequestOut)
def decline_card_request(
    request_id: uuid.UUID,
    payload: schemas.DeclineIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    row = _get_card_request(db, _staff_tenant(user), request_id)
    row = card_request_service.decline(db, tenant, row, payload.vendor_note)
    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="card_request.decline",
        entity_type="card_request",
        entity_id=row.id,
        summary=f"Declined {row.public_ref}",
        data={"vendor_note": row.vendor_note},
    )
    db.commit()
    return serializers.staff_card_request_out(row, tenant)


@router.post("/card-requests/{request_id}/convert", response_model=schemas.StaffCardRequestOut)
def convert_card_request(
    request_id: uuid.UUID,
    payload: schemas.ConvertIn,
    user: models.User = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    row = _get_card_request(db, _staff_tenant(user), request_id)
    row, reservation = card_request_service.convert(db, tenant, row, payload.quantity)
    audit.record(
        db,
        tenant_id=_staff_tenant(user),
        actor_id=user.id,
        action="card_request.convert",
        entity_type="card_request",
        entity_id=row.id,
        summary=f"Converted {row.public_ref} into reservation {reservation.public_ref}",
        data={"reservation_id": str(reservation.id), "reservation_ref": reservation.public_ref},
    )
    db.commit()
    return serializers.staff_card_request_out(row, tenant)


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
            models.Stock.archived_at.is_(None),
            models.Stock.is_online.is_(True),
            (models.Stock.quantity - models.Stock.reserved) <= 2,
        )
    )
    open_requests = db.scalar(
        select(func.count())
        .select_from(models.CardRequest)
        .where(
            models.CardRequest.tenant_id == _staff_tenant(user),
            models.CardRequest.status.in_(card_request_service.ACTIVE_STATUSES),
        )
    )
    stale = db.scalar(
        select(func.count())
        .select_from(models.Stock)
        .where(
            models.Stock.tenant_id == _staff_tenant(user),
            models.Stock.archived_at.is_(None),
            models.Stock.is_online.is_(True),
            models.Stock.updated_at < now - timedelta(days=7),
        )
    )

    return schemas.DashboardOut(
        pending_reservations=int(pending or 0),
        active_reservations=int(active or 0),
        open_requests=int(open_requests or 0),
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
    return serializers.staff_shop_out(tenant)


@router.patch("/settings", response_model=schemas.StaffShopOut)
def update_settings(
    payload: schemas.SettingsUpdateIn,
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, user)
    settings_row = tenant.settings
    if settings_row is None:
        settings_row = models.TenantSettings(tenant_id=tenant.id)
        db.add(settings_row)

    changes = payload.model_dump(exclude_unset=True)
    repriced_stock = None
    stock_without_scryfall_prices = None
    pricing_fields = {
        "scryfall_pricing_enabled",
        "scryfall_min_price_minor",
        "scryfall_markup_percent",
        "scryfall_rounding_increment",
    }
    pricing_changes = pricing_fields.intersection(changes)
    if pricing_changes:
        current = settings_row.scryfall_pricing if isinstance(settings_row.scryfall_pricing, dict) else {}
        pricing = {
            "enabled": current.get("enabled") is True,
            "minimum_price_minor": current.get("minimum_price_minor", 0),
            "markup_percent": current.get("markup_percent", 0),
            "rounding_increment_minor": current.get("rounding_increment_minor", 500),
        }
        if "scryfall_pricing_enabled" in changes:
            pricing["enabled"] = changes.pop("scryfall_pricing_enabled")
        if "scryfall_min_price_minor" in changes:
            pricing["minimum_price_minor"] = changes.pop("scryfall_min_price_minor")
        if "scryfall_markup_percent" in changes:
            pricing["markup_percent"] = changes.pop("scryfall_markup_percent")
        if "scryfall_rounding_increment" in changes:
            pricing["rounding_increment_minor"] = changes.pop("scryfall_rounding_increment") * 100
        settings_row.scryfall_pricing = pricing
        changes["scryfall_pricing"] = pricing

        if pricing["enabled"]:
            normalized = scryfall_pricing.pricing_settings(settings_row)
            if normalized is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="A minimum price and markup percentage are required to enable Scryfall pricing.",
                )
            try:
                updated, skipped = scryfall_pricing.reprice_tenant_stock(db, tenant, normalized)
            except exchange_rate_service.ExchangeRateError as exc:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
            repriced_stock = updated
            stock_without_scryfall_prices = skipped
            changes["repriced_stock"] = updated
            changes["stock_without_scryfall_prices"] = skipped

    for field, value in changes.items():
        if field not in ("scryfall_pricing", "repriced_stock", "stock_without_scryfall_prices"):
            setattr(settings_row, field, value)
    if changes:
        audit.record(
            db,
            tenant_id=tenant.id,
            actor_id=user.id,
            action="settings.update",
            entity_type="shop",
            entity_id=tenant.id,
            summary=f"Updated shop settings ({', '.join(sorted(changes))})",
            data=changes,
        )
    db.commit()
    db.refresh(tenant)
    return serializers.staff_shop_out(tenant, repriced_stock, stock_without_scryfall_prices)


@router.post("/settings/scryfall-refresh", response_model=schemas.ScryfallRefreshOut)
def refresh_scryfall_prices(
    request: Request,
    user: models.User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Fetch current Scryfall market prices for stocked cards and reprice."""
    tenant = _tenant(db, user)
    pricing = scryfall_pricing.pricing_settings(tenant.settings)
    if pricing is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A minimum price and markup percentage are required before refreshing prices.",
        )
    ratelimit.enforce(
        request,
        scope="scryfall-refresh",
        limit=settings.scryfall_refresh_ip_limit,
        window_seconds=settings.scryfall_refresh_ip_window_seconds,
    )
    try:
        refreshed, unavailable = scryfall_pricing.refresh_stock_market_prices(db, tenant)
        updated, skipped = scryfall_pricing.reprice_tenant_stock(db, tenant, pricing)
    except scryfall_pricing.ScryfallUnavailableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except exchange_rate_service.ExchangeRateError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    audit.record(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="stock.reprice",
        entity_type="shop",
        entity_id=tenant.id,
        summary=(f"Refreshed Scryfall prices: {updated} stock rows repriced, {skipped} rows without a market price"),
        data={
            "cards_refreshed": refreshed,
            "cards_unavailable": unavailable,
            "repriced_stock": updated,
            "stock_without_scryfall_prices": skipped,
        },
    )
    db.commit()
    return schemas.ScryfallRefreshOut(
        cards_refreshed=refreshed,
        cards_unavailable=unavailable,
        repriced_stock=updated,
        stock_without_scryfall_prices=skipped,
    )
