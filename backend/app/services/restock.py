"""Restock alerts: subscribe, and notify when a variant returns."""

from __future__ import annotations

from sqlalchemy import select

from app import models
from app.services import notifications


def notify_waiting(db, tenant: models.Tenant, stock: models.Stock) -> int:
    """Queue a restock email for everyone waiting on this variant.

    Called inside stock-increasing transactions. Alerts are one-shot: once
    notified, the customer subscribes again if they still want it later.
    """
    if not stock.is_online or stock.available <= 0:
        return 0

    alerts = list(
        db.scalars(
            select(models.RestockAlert).where(
                models.RestockAlert.tenant_id == tenant.id,
                models.RestockAlert.card_id == stock.card_id,
                models.RestockAlert.finish == stock.finish,
                models.RestockAlert.condition == stock.condition,
                models.RestockAlert.language == stock.language,
                models.RestockAlert.notified_at.is_(None),
            )
        ).all()
    )
    if not alerts:
        return 0

    card = stock.card
    now = models.utcnow()
    for alert in alerts:
        notifications.enqueue(
            db,
            tenant.id,
            "RESTOCK_AVAILABLE",
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
            },
            recipient=alert.email,
        )
        alert.notified_at = now
    return len(alerts)
