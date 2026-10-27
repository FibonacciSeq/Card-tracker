"""Deliver queued email notifications with retry and backoff.

Run with ``python -m app.workers.notifications``. The default console backend
prints messages to the worker log, which is enough to verify the pipeline
before an SMTP provider is configured.
"""

from __future__ import annotations

import logging
import smtplib
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import SessionLocal, set_tenant_context
from app.services import notifications

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 10
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600


class Sender(Protocol):
    def send(self, *, recipient: str, subject: str, body: str) -> None: ...


class ConsoleSender:
    def send(self, *, recipient: str, subject: str, body: str) -> None:
        logger.info("Email to %s | %s\n%s", recipient, subject, body)


class SmtpSender:
    def __init__(self) -> None:
        if not settings.smtp_host:
            raise RuntimeError("CARDTRACKER_SMTP_HOST is required for the smtp backend")

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


def default_sender() -> Sender:
    backend = settings.notification_backend.lower().strip()
    if backend == "smtp":
        return SmtpSender()
    if backend in ("console", "log"):
        return ConsoleSender()
    raise RuntimeError(f"Unknown CARDTRACKER_NOTIFICATION_BACKEND: {backend!r}")


def deliver_tenant(
    db: Session,
    tenant: models.Tenant,
    sender: Sender,
    *,
    now: datetime,
    limit: int = 50,
) -> int:
    pending = list(
        db.scalars(
            select(models.Notification)
            .where(
                models.Notification.tenant_id == tenant.id,
                models.Notification.channel == "email",
                models.Notification.recipient.is_not(None),
                models.Notification.sent_at.is_(None),
                models.Notification.attempts < settings.notification_max_attempts,
                or_(
                    models.Notification.next_attempt_at.is_(None),
                    models.Notification.next_attempt_at <= now,
                ),
            )
            .order_by(models.Notification.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )

    delivered = 0
    for row in pending:
        try:
            subject, body = notifications.render(row, tenant)
            assert row.recipient is not None
            sender.send(recipient=row.recipient, subject=subject, body=body)
        except Exception as exc:  # one bad address must not stall the queue
            row.attempts += 1
            row.error = f"{type(exc).__name__}: {exc}"[:1000]
            if row.attempts < settings.notification_max_attempts:
                delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (row.attempts - 1))
                row.next_attempt_at = now + timedelta(seconds=delay)
            logger.warning("Notification %s failed (attempt %s): %s", row.id, row.attempts, row.error)
        else:
            row.sent_at = now
            row.error = None
            delivered += 1

    if pending:
        db.commit()
    return delivered


def run_once(
    *,
    sender: Sender | None = None,
    now: datetime | None = None,
    limit_per_tenant: int = 50,
) -> int:
    sender = sender or default_sender()
    now = now or datetime.now(UTC)
    delivered = 0
    with SessionLocal() as db:
        tenants = list(db.scalars(select(models.Tenant)).all())
        for tenant in tenants:
            # RLS is transaction-scoped; enter each tenant before reading.
            set_tenant_context(db, tenant.id)
            delivered += deliver_tenant(db, tenant, sender, now=now, limit=limit_per_tenant)
    return delivered


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Notification worker started (backend=%s)", settings.notification_backend)
    while True:
        try:
            delivered = run_once()
            if delivered:
                logger.info("Delivered %s notification(s)", delivered)
        except Exception:
            logger.exception("Notification worker failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
