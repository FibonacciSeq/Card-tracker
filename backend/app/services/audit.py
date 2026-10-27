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
