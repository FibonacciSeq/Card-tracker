"""Audit trail helpers.

Events join the caller's transaction, so a rolled-back change leaves no
misleading record behind.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app import models


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    summary: str,
    data: dict | None = None,
) -> models.AuditEvent:
    event = models.AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        summary=summary[:500],
        data=data or {},
    )
    db.add(event)
    return event


def record_customer(
    db: Session,
    *,
    customer_id: uuid.UUID,
    action: str,
    summary: str,
    entity_type: str = "customer",
    entity_id: str | uuid.UUID | None = None,
    data: dict | None = None,
) -> models.CustomerAuditEvent:
    """Record a global customer account/session event.

    These rows are intentionally separate from the tenant audit trail: one
    customer can act across many shops, so a tenant-scoped audit row would
    either leak the event to a shop or lose it entirely.
    """
    event = models.CustomerAuditEvent(
        user_id=customer_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or customer_id),
        summary=summary[:500],
        data=data or {},
    )
    db.add(event)
    return event
