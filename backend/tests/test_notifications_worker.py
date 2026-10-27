from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.services import notifications
from app.workers import notifications as worker


class RecordingSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self.error = error

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append({"recipient": recipient, "subject": subject, "body": body})


def _ready_payload(ref: str = "R-ABC123") -> dict:
    return {
        "public_ref": ref,
        "status": "READY",
        "customer_name": "Ana",
        "expires_at": "2026-10-29T12:00:00+00:00",
    }


def _enqueue(db, tenant, *, recipient="customer@example.com", payload=None, kind="RESERVATION_READY"):
    row = notifications.enqueue(
        db, tenant.id, kind, payload if payload is not None else _ready_payload(), recipient=recipient
    )
    db.commit()
    return row


def test_delivers_pending_email_and_marks_it_sent(db, tenant):
    row = _enqueue(db, tenant)
    sender = RecordingSender()
    now = datetime.now(UTC)

    assert worker.deliver_tenant(db, tenant, sender, now=now) == 1
    assert sender.sent[0]["recipient"] == "customer@example.com"
    assert "R-ABC123" in sender.sent[0]["subject"]
    assert "ready for pickup" in sender.sent[0]["body"]

    db.refresh(row)
    assert row.sent_at is not None
    assert row.error is None


def test_failure_backs_off_then_retries(db, tenant):
    row = _enqueue(db, tenant)
    now = datetime.now(UTC)

    failing = RecordingSender(RuntimeError("smtp down"))
    assert worker.deliver_tenant(db, tenant, failing, now=now) == 0
    db.refresh(row)
    assert row.attempts == 1
    assert row.sent_at is None
    assert row.error and "smtp down" in row.error
    assert row.next_attempt_at is not None

    # Still inside the 60s backoff window.
    assert worker.deliver_tenant(db, tenant, RecordingSender(), now=now + timedelta(seconds=30)) == 0

    recovered = RecordingSender()
    assert worker.deliver_tenant(db, tenant, recovered, now=now + timedelta(seconds=61)) == 1
    db.refresh(row)
    assert row.sent_at is not None
    assert row.error is None
    assert len(recovered.sent) == 1


def test_stops_retrying_after_the_attempt_limit(db, tenant, monkeypatch):
    monkeypatch.setattr(settings, "notification_max_attempts", 1)
    row = _enqueue(db, tenant)
    now = datetime.now(UTC)

    assert worker.deliver_tenant(db, tenant, RecordingSender(RuntimeError("boom")), now=now) == 0
    db.refresh(row)
    assert row.attempts == 1

    later = RecordingSender()
    assert worker.deliver_tenant(db, tenant, later, now=now + timedelta(days=1)) == 0
    assert later.sent == []


def test_in_app_notifications_are_not_emailed(db, tenant):
    notifications.enqueue(db, tenant.id, "RESERVATION_CREATED", {}, recipient=None)
    db.commit()

    sender = RecordingSender()
    assert worker.deliver_tenant(db, tenant, sender, now=datetime.now(UTC)) == 0
    assert sender.sent == []


def test_run_once_drains_each_tenant(db, tenant, other_tenant, monkeypatch):
    _enqueue(db, tenant, recipient="ana@example.com")
    _enqueue(db, other_tenant, recipient="marko@example.com")
    db.commit()

    maker = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", maker)

    sender = RecordingSender()
    assert worker.run_once(sender=sender) == 2
    assert {item["recipient"] for item in sender.sent} == {"ana@example.com", "marko@example.com"}


def test_render_staff_alert_mentions_the_customer(db, tenant):
    row = _enqueue(
        db,
        tenant,
        kind="RESERVATION_CREATED",
        payload={
            "public_ref": "R-ZZZ999",
            "customer_name": "Ana",
            "line_count": 2,
            "total_minor": 250000,
            "currency": "RSD",
            "expires_at": "2026-10-29T12:00:00+00:00",
        },
    )
    subject, body = notifications.render(row, tenant)
    assert "New reservation R-ZZZ999" in subject
    assert "Ana requested 2 card line(s)" in body
    assert "2500.00 RSD" in body
