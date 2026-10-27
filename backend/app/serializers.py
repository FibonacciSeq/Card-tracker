"""Convert ORM objects into API response schemas."""

from __future__ import annotations

from app import models, schemas


def shop_out(tenant: models.Tenant) -> schemas.ShopOut:
    settings = tenant.settings
    return schemas.ShopOut(
        slug=tenant.slug,
        name=tenant.name,
        locale=tenant.locale,
        currency=tenant.currency,
        timezone=tenant.timezone,
        brand_name=settings.brand_name if settings else None,
        logo_url=settings.logo_url if settings else None,
        colors=settings.colors if settings else {},
        hero=settings.hero if settings else {},
        contact=settings.contact if settings else {},
        hours=settings.hours if settings else {},
        payment_instructions=settings.payment_instructions if settings else "",
        hold_hours=settings.hold_hours if settings else 24,
        allow_backorders=settings.allow_backorders if settings else False,
        directory_opt_in=settings.directory_opt_in if settings else False,
    )


def staff_shop_out(tenant: models.Tenant) -> schemas.StaffShopOut:
    """Public shop profile plus settings only staff may see."""
    base = shop_out(tenant)
    return schemas.StaffShopOut(
        **base.model_dump(),
        notification_email=tenant.settings.notification_email if tenant.settings else None,
    )


def card_out(card: models.Card) -> schemas.CardOut:
    return schemas.CardOut.model_validate(card)


def stock_item_out(stock: models.Stock, card: models.Card | None = None) -> schemas.StockItemOut:
    return schemas.StockItemOut(
        stock_id=stock.id,
        card=card_out(card or stock.card),
        finish=stock.finish,
        condition=stock.condition,
        language=stock.language,
        price=schemas.Money(amount_minor=stock.price_minor, currency=stock.currency),
        available=stock.available,
        is_online=stock.is_online,
        updated_at=stock.updated_at,
    )


def staff_stock_out(stock: models.Stock, sold_30d: int = 0, restock_waiting: int = 0) -> schemas.StaffStockOut:
    return schemas.StaffStockOut(
        stock_id=stock.id,
        card=card_out(stock.card),
        finish=stock.finish,
        condition=stock.condition,
        language=stock.language,
        on_hand=stock.quantity,
        reserved=stock.reserved,
        available=stock.available,
        sold_30d=sold_30d,
        restock_waiting=restock_waiting,
        price=schemas.Money(amount_minor=stock.price_minor, currency=stock.currency),
        is_online=stock.is_online,
        updated_at=stock.updated_at,
    )


def line_out(line: models.ReservationLine) -> schemas.ReservationLineOut:
    return schemas.ReservationLineOut(
        line_id=line.id,
        stock_id=line.stock_id,
        name=line.name,
        set_code=line.set_code,
        collector_number=line.collector_number,
        finish=line.finish,
        condition=line.condition,
        language=line.language,
        quantity=line.quantity,
        completed_quantity=line.completed_quantity,
        cancelled_quantity=line.cancelled_quantity,
        unit_price=schemas.Money(amount_minor=line.unit_price_minor, currency=line.currency),
    )


def reservation_out(
    reservation: models.Reservation,
    tenant: models.Tenant,
    access_token: str | None = None,
) -> schemas.ReservationOut:
    return schemas.ReservationOut(
        id=reservation.id,
        public_ref=reservation.public_ref,
        status=reservation.status,
        expires_at=reservation.expires_at,
        created_at=reservation.created_at,
        total=schemas.Money(amount_minor=reservation.total_minor, currency=reservation.currency),
        shop={"slug": tenant.slug, "name": tenant.name},
        customer_name=reservation.customer_name,
        lines=[line_out(line) for line in reservation.lines],
        access_token=access_token,
    )


def staff_reservation_out(reservation: models.Reservation, tenant: models.Tenant) -> schemas.StaffReservationOut:
    """Same shape as the public view plus the details staff need to respond."""
    base = reservation_out(reservation, tenant)
    return schemas.StaffReservationOut(
        **base.model_dump(),
        customer_email=reservation.email,
        customer_phone=reservation.phone,
        note=reservation.note,
    )


def reservation_summary_out(reservation: models.Reservation) -> schemas.ReservationSummaryOut:
    return schemas.ReservationSummaryOut(
        id=reservation.id,
        public_ref=reservation.public_ref,
        customer_name=reservation.customer_name,
        status=reservation.status,
        expires_at=reservation.expires_at,
        created_at=reservation.created_at,
        total=schemas.Money(amount_minor=reservation.total_minor, currency=reservation.currency),
        line_count=len(reservation.lines),
    )


def card_request_out(
    row: models.CardRequest,
    tenant: models.Tenant,
    access_token: str | None = None,
) -> schemas.CardRequestOut:
    target = (
        schemas.Money(amount_minor=row.target_price_minor, currency=row.currency)
        if row.target_price_minor is not None
        else None
    )
    quote = (
        schemas.Money(amount_minor=row.quote_price_minor, currency=row.quote_currency or row.currency)
        if row.quote_price_minor is not None
        else None
    )
    return schemas.CardRequestOut(
        id=row.id,
        public_ref=row.public_ref,
        status=row.status,
        card_id=row.card_id,
        requested_name=row.requested_name,
        set_code=row.set_code,
        collector_number=row.collector_number,
        finish=row.finish,
        condition=row.condition,
        language=row.language,
        quantity=row.quantity,
        target_price=target,
        quote_price=quote,
        quote_expires_at=row.quote_expires_at,
        vendor_note=row.vendor_note,
        customer_name=row.customer_name,
        reservation_id=row.reservation_id,
        reservation_ref=row.reservation.public_ref if row.reservation else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        access_token=access_token,
    )


def staff_card_request_out(row: models.CardRequest, tenant: models.Tenant) -> schemas.StaffCardRequestOut:
    base = card_request_out(row, tenant)
    return schemas.StaffCardRequestOut(
        **base.model_dump(exclude={"access_token"}),
        customer_email=row.email,
        customer_phone=row.phone,
        customer_note=row.customer_note,
    )


def restock_alert_out(row: models.RestockAlert, *, already_subscribed: bool = False) -> schemas.RestockAlertOut:
    return schemas.RestockAlertOut(
        id=row.id,
        card_id=row.card_id,
        email=row.email,
        finish=row.finish,
        condition=row.condition,
        language=row.language,
        already_subscribed=already_subscribed,
        created_at=row.created_at,
    )
