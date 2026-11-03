from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.services import notifications, push
from app.workers import notifications as worker


class RecordingPushSender:
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.failures = failures or {}
        self.sent: list[dict] = []

    def send(self, *, token, platform, title, body, url=None) -> None:
        failure = self.failures.get(token)
        if failure is not None:
            raise failure
        self.sent.append(
            {
                "token": token,
                "platform": platform,
                "title": title,
                "body": body,
                "url": url,
            }
        )


@pytest.fixture
def customer(db, tenant):
    row = models.User(
        id=uuid.uuid4(),
        tenant_id=None,
        email=f"customer-{uuid.uuid4().hex}@example.com",
        password_hash=None,
        role="customer",
        display_name="Ana",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _token(db, customer, token: str = "device-token", platform: str = "android"):
    row = models.PushToken(
        id=uuid.uuid4(),
        user_id=customer.id,
        token=token,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        platform=platform,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _push_row(db, tenant, customer, **kwargs):
    row = models.Notification(
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="RESERVATION_READY",
        payload={
            "public_ref": "R-ABC123",
            "expires_at": "2026-11-03T12:00:00+00:00",
        },
        channel="push",
        **kwargs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_deliver_push_sends_to_every_active_token(db, tenant, customer):
    _token(db, customer, "android-token", "android")
    _token(db, customer, "ios-token", "ios")
    row = _push_row(db, tenant, customer)
    sender = RecordingPushSender()
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

    assert worker.deliver_push(db, tenant, sender, now=now) == 1

    db.refresh(row)
    assert row.sent_at == now.replace(tzinfo=None)
    assert row.error is None
    assert [item["platform"] for item in sender.sent] == ["android", "ios"]
    assert sender.sent[0]["url"] == "https://app.cardtracker.local/shop/bolt-shop"
    assert sender.sent[0]["title"] == "Your cards are ready — R-ABC123"


def test_deliver_push_marks_a_queued_row_sent_when_no_token_exists(db, tenant, customer):
    row = _push_row(db, tenant, customer)

    assert worker.deliver_push(db, tenant, RecordingPushSender(), now=datetime(2026, 11, 2, tzinfo=UTC)) == 0

    db.refresh(row)
    assert row.sent_at is not None
    assert row.error == "No active push token"


def test_deliver_push_ignores_a_revoked_token(db, tenant, customer):
    token = _token(db, customer)
    token.revoked_at = datetime(2026, 11, 1, tzinfo=UTC)
    db.commit()
    row = _push_row(db, tenant, customer)

    assert worker.deliver_push(db, tenant, RecordingPushSender(), now=datetime(2026, 11, 2, tzinfo=UTC)) == 0

    db.refresh(row)
    assert row.sent_at is not None
    assert row.error == "No active push token"


def test_deliver_push_revokes_a_rejected_token(db, tenant, customer):
    token = _token(db, customer)
    row = _push_row(db, tenant, customer)
    now = datetime(2026, 11, 2, tzinfo=UTC)
    sender = RecordingPushSender({"device-token": push.PushTokenInvalid("gone")})

    assert worker.deliver_push(db, tenant, sender, now=now) == 0

    db.refresh(token)
    db.refresh(row)
    assert token.revoked_at == now.replace(tzinfo=None)
    assert row.sent_at == now.replace(tzinfo=None)
    assert row.attempts == 1
    assert "PushTokenInvalid" in row.error


def test_deliver_push_retries_transient_failures_and_keeps_the_token(db, tenant, customer):
    token = _token(db, customer)
    row = _push_row(db, tenant, customer)
    now = datetime(2026, 11, 2, tzinfo=UTC)
    sender = RecordingPushSender({"device-token": push.PushTransientError("network down")})

    assert worker.deliver_push(db, tenant, sender, now=now) == 0

    db.refresh(row)
    db.refresh(token)
    assert row.sent_at is None
    assert row.attempts == 1
    assert row.next_attempt_at == (now + timedelta(seconds=60)).replace(tzinfo=None)
    assert "PushTransientError" in row.error
    assert token.revoked_at is None

    row.next_attempt_at = now - timedelta(seconds=1)
    db.commit()
    assert worker.deliver_push(db, tenant, RecordingPushSender(), now=now) == 1
    db.refresh(row)
    assert row.sent_at == now.replace(tzinfo=None)


def test_deliver_push_stops_after_the_attempt_limit(db, tenant, customer, monkeypatch):
    _token(db, customer)
    row = _push_row(db, tenant, customer)
    now = datetime(2026, 11, 2, tzinfo=UTC)
    monkeypatch.setattr(settings, "notification_max_attempts", 1)
    sender = RecordingPushSender({"device-token": push.PushTransientError("network down")})

    assert worker.deliver_push(db, tenant, sender, now=now) == 0

    db.refresh(row)
    assert row.attempts == 1
    assert row.sent_at == now.replace(tzinfo=None)
    assert row.next_attempt_at is None


def test_deliver_push_is_successful_when_any_token_succeeds(db, tenant, customer):
    bad = _token(db, customer, "bad-token")
    good = _token(db, customer, "good-token")
    row = _push_row(db, tenant, customer)
    now = datetime(2026, 11, 2, tzinfo=UTC)
    sender = RecordingPushSender({"bad-token": push.PushTokenInvalid("gone")})

    assert worker.deliver_push(db, tenant, sender, now=now) == 1

    db.refresh(row)
    db.refresh(bad)
    assert row.sent_at == now.replace(tzinfo=None)
    assert bad.revoked_at == now.replace(tzinfo=None)
    assert good.revoked_at is None
    assert [item["token"] for item in sender.sent] == ["good-token"]


def test_deliver_push_returns_zero_when_nothing_is_due(db, tenant, customer):
    assert worker.deliver_push(db, tenant, RecordingPushSender(), now=datetime(2026, 11, 2, tzinfo=UTC)) == 0


def test_enqueue_adds_a_push_row_for_a_signed_in_customer(db, tenant, customer):
    notifications.enqueue(
        db,
        tenant.id,
        "RESERVATION_READY",
        {"public_ref": "R-XYZ"},
        recipient="customer@example.com",
        user_id=customer.id,
        push=True,
    )
    db.commit()

    rows = list(db.scalars(select(models.Notification)).all())
    assert len(rows) == 2
    assert {row.channel for row in rows} == {"email", "push"}
    push_row = next(row for row in rows if row.channel == "push")
    assert push_row.user_id == customer.id
    assert push_row.recipient is None


def test_enqueue_does_not_add_push_without_a_customer(db, tenant):
    notifications.enqueue(
        db,
        tenant.id,
        "RESERVATION_READY",
        {"public_ref": "R-XYZ"},
        recipient="customer@example.com",
        push=True,
    )
    db.commit()

    rows = list(db.scalars(select(models.Notification)).all())
    assert [row.channel for row in rows] == ["email"]


def test_run_once_can_deliver_push_without_an_email_sender(db, tenant, other_tenant, customer, monkeypatch):
    _token(db, customer)
    row = _push_row(db, tenant, customer)
    maker = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", maker)
    monkeypatch.setattr(worker, "default_sender", lambda: None)
    sender = RecordingPushSender()

    assert worker.run_once(push_sender=sender) == 1

    db.refresh(row)
    assert row.sent_at is not None
    assert [item["token"] for item in sender.sent] == ["device-token"]
