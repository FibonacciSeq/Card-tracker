"""Restock alerts: subscribe, and notify when a variant returns."""

from __future__ import annotations

from sqlalchemy import select

from app import models
from app.constants import RESTOCK_AVAILABLE
from app.services import notifications


def notify_waiting(db, tenant: models.Tenant, stock: models.Stock) -> int:
    """Queue a restock email for everyone waiting on this variant.

    Called inside stock-increasing transactions. Alerts are one-shot: once
    notified, the customer subscribes again if they still want it later.
    """
    if stock.archived_at is not None or not stock.is_online or stock.available <= 0:
        return 0

    alerts = list(
        db.scalars(
            select(models.RestockAlert)
            .where(
                models.RestockAlert.tenant_id == tenant.id,
                models.RestockAlert.card_id == stock.card_id,
                models.RestockAlert.finish == stock.finish,
                models.RestockAlert.condition == stock.condition,
                models.RestockAlert.language == stock.language,
                models.RestockAlert.notified_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    if not alerts:
        return 0

    card = stock.card
    now = models.utcnow()
    notified = 0
    for alert in alerts:
        if alert.customer_id is None:
            # Guests have no account to notify, and event email is reserved
            # for account security. Their alert stays pending until they sign
            # in and claim it.
            continue
        notifications.enqueue(
            db,
            tenant.id,
            RESTOCK_AVAILABLE,
            {
                "name": card.name,
                "set_code": card.set_code,
                "collector_number": card.collector_number,
                "finish": stock.finish,
                "condition": stock.condition,
                "language": stock.language,
                "price_minor": stock.price_minor,
                "currency": stock.currency,
                "stock_id": str(stock.id),
                "shop_slug": tenant.slug,
                "alert_id": str(alert.id),
            },
            user_id=alert.customer_id,
            push=True,
        )
        alert.notified_at = now
        notified += 1
    return notified
