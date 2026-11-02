"""Deliver queued email notifications with retry and backoff.

Run with ``python -m app.workers.notifications``. The default console backend
prints messages to the worker log, which is enough to verify the pipeline
before an SMTP provider is configured.
"""

from __future__ import annotations

import logging
import smtplib
import time
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import SessionLocal, set_push_worker_context, set_tenant_context
from app.security import derive_otp_code
from app.services import notifications, push

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 10
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600


class Sender(Protocol):
    def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> None: ...


class ConsoleSender:
    def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        # Development convenience only: never log the recipient or body, which
        # contain customer PII and order details. The subject is enough to
        # verify the pipeline.
        logger.info("Email notification rendered: %s", subject)


class SmtpSender:
    def __init__(self) -> None:
        if not settings.smtp_host:
            raise RuntimeError("CARDTRACKER_SMTP_HOST is required for the smtp backend")

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        for key, value in (headers or {}).items():
            message[key] = value
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


def default_sender() -> Sender | None:
    backend = settings.notification_backend.lower().strip()
    if backend == "smtp":
        return SmtpSender()
    if backend in ("console", "log"):
        return ConsoleSender()
    if backend == "none":
        return None
    raise RuntimeError(f"Unknown CARDTRACKER_NOTIFICATION_BACKEND: {backend!r}")


def deliver_otp_challenges(
    db: Session,
    sender: Sender,
    *,
    now: datetime,
    limit: int = 50,
) -> int:
    """Drain the global OTP outbox.

    OTP challenges are not tenant-owned, so this runs once per worker pass,
    outside any tenant context.
    """
    pending = list(
        db.scalars(
            select(models.CustomerOtpChallenge)
            .where(
                models.CustomerOtpChallenge.consumed_at.is_(None),
                models.CustomerOtpChallenge.expires_at > now,
                models.CustomerOtpChallenge.email_sent_at.is_(None),
                models.CustomerOtpChallenge.email_attempts < settings.otp_email_max_attempts,
                or_(
                    models.CustomerOtpChallenge.next_email_attempt_at.is_(None),
                    models.CustomerOtpChallenge.next_email_attempt_at <= now,
                ),
            )
            .order_by(models.CustomerOtpChallenge.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )

    delivered = 0
    for challenge in pending:
        try:
            code = derive_otp_code(challenge.id, challenge.email)
            subject, body = notifications.render_otp(code, settings.otp_expiry_seconds)
            sender.send(recipient=challenge.email, subject=subject, body=body)
        except Exception as exc:
            challenge.email_attempts += 1
            error_type = type(exc).__name__
            smtp_code = getattr(exc, "smtp_code", None)
            if isinstance(smtp_code, int):
                error_type = f"{error_type} ({smtp_code})"
            challenge.email_error = f"{error_type}: delivery failed"[:1000]
            if challenge.email_attempts < settings.otp_email_max_attempts:
                delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (challenge.email_attempts - 1))
                challenge.next_email_attempt_at = now + timedelta(seconds=delay)
            logger.warning(
                "OTP challenge %s failed (attempt %s): %s",
                challenge.id,
                challenge.email_attempts,
                error_type,
            )
        else:
            challenge.email_sent_at = now
            challenge.email_error = None
            delivered += 1

    if pending:
        db.commit()
    return delivered


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
            sender.send(
                recipient=row.recipient,
                subject=subject,
                body=body,
                headers=notifications.headers(row, tenant),
            )
        except Exception as exc:  # one bad address must not stall the queue
            row.attempts += 1
            # SMTP exceptions can embed the recipient address. Store only the
            # type (and SMTP status code when present) so neither the database
            # nor the worker log becomes a PII sink.
            error_type = type(exc).__name__
            smtp_code = getattr(exc, "smtp_code", None)
            if isinstance(smtp_code, int):
                error_type = f"{error_type} ({smtp_code})"
            row.error = f"{error_type}: delivery failed"[:1000]
            if row.attempts < settings.notification_max_attempts:
                delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (row.attempts - 1))
                row.next_attempt_at = now + timedelta(seconds=delay)
            else:
                # A permanently failed restock email should not consume the
                # one-shot alert. Clear the marker so the next stock increase
                # can try again.
                alert_id = (row.payload or {}).get("alert_id")
                if alert_id:
                    try:
                        alert = db.get(models.RestockAlert, uuid.UUID(str(alert_id)))
                    except ValueError:
                        alert = None
                    if alert is not None and alert.tenant_id == row.tenant_id:
                        alert.notified_at = None
            logger.warning("Notification %s failed (attempt %s): %s", row.id, row.attempts, error_type)
        else:
            row.sent_at = now
            row.error = None
            delivered += 1

    if pending:
        db.commit()
    return delivered


def deliver_push(
    db: Session,
    tenant: models.Tenant,
    sender: push.PushSender,
    *,
    now: datetime,
    limit: int = 50,
) -> int:
    set_push_worker_context(db)
    pending = list(
        db.scalars(
            select(models.Notification)
            .where(
                models.Notification.tenant_id == tenant.id,
                models.Notification.channel == "push",
                models.Notification.user_id.is_not(None),
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
    if not pending:
        return 0

    delivered = 0
    for row in pending:
        tokens = list(
            db.scalars(
                select(models.PushToken).where(
                    models.PushToken.user_id == row.user_id,
                    models.PushToken.revoked_at.is_(None),
                )
            ).all()
        )
        if not tokens:
            row.sent_at = now
            row.error = "No active push token"
            continue

        subject, body = notifications.render(row, tenant)
        url = notifications.app_card_url(tenant, row.payload or {})
        successes = 0
        invalid = 0
        errors: list[str] = []
        for token in tokens:
            try:
                sender.send(
                    token=token.token,
                    platform=token.platform,
                    title=subject,
                    body=body,
                    url=url,
                )
            except push.PushTokenInvalid as exc:
                invalid += 1
                token.revoked_at = now
                errors.append(f"{type(exc).__name__}: {exc}")
            except push.PushTransientError as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
            else:
                successes += 1

        if successes:
            row.sent_at = now
            row.error = None
            delivered += 1
            continue

        row.attempts += 1
        row.error = ("; ".join(errors) or "Push delivery failed")[:1000]
        if invalid == len(tokens):
            # The device is gone; do not retry until it registers a new token.
            row.sent_at = now
        elif row.attempts < settings.notification_max_attempts:
            delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (row.attempts - 1))
            row.next_attempt_at = now + timedelta(seconds=delay)
        else:
            row.sent_at = now

    db.commit()
    return delivered


def run_once(
    *,
    sender: Sender | None = None,
    push_sender: push.PushSender | None = None,
    now: datetime | None = None,
    limit_per_tenant: int = 50,
) -> int:
    sender = sender if sender is not None else default_sender()
    push_sender = push_sender if push_sender is not None else push.default_sender()
    if sender is None and push_sender is None:
        # `none` is a supported deployment mode: leave the outbox untouched so
        # enabling a provider later drains it instead of losing messages.
        return 0
    now = now or datetime.now(UTC)
    delivered = 0
    with SessionLocal() as db:
        if sender is not None:
            delivered += deliver_otp_challenges(db, sender, now=now, limit=limit_per_tenant)
        tenants = list(db.scalars(select(models.Tenant)).all())
        for tenant in tenants:
            # RLS is transaction-scoped; enter each tenant before reading.
            set_tenant_context(db, tenant.id)
            if sender is not None:
                delivered += deliver_tenant(db, tenant, sender, now=now, limit=limit_per_tenant)
            if push_sender is not None:
                delivered += deliver_push(db, tenant, push_sender, now=now, limit=limit_per_tenant)
    return delivered


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info(
        "Notification worker started (email=%s push=%s)",
        settings.notification_backend,
        settings.push_backend,
    )
    sender = default_sender()
    push_sender = push.default_sender()
    while True:
        try:
            delivered = run_once(sender=sender, push_sender=push_sender)
            if delivered:
                logger.info("Delivered %s notification(s)", delivered)
        except Exception:
            logger.exception("Notification worker failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
