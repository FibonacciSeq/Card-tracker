from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import models
from app.security import create_customer_access_token


def _customer(db, email: str | None = None) -> models.User:
    user = models.User(
        tenant_id=None,
        email=email or f"customer-{uuid.uuid4().hex}@example.com",
        role="customer",
        is_active=True,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(user: models.User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_customer_access_token(user.id)}"}


def _notification(
    db,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: str = "RESERVATION_READY",
    channel: str = "push",
    payload: dict | None = None,
    attempts: int = 0,
    sent_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
    error: str | None = None,
    created_at: datetime | None = None,
) -> models.Notification:
    row = models.Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        kind=kind,
        channel=channel,
        payload=payload or {"public_ref": "R-ABC123", "expires_at": "2026-11-07T12:00:00+00:00"},
        attempts=attempts,
        sent_at=sent_at,
        next_attempt_at=next_attempt_at,
        error=error,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_notification_log_lists_statuses_and_paginates(client, db, tenant, other_tenant):
    customer = _customer(db)
    other = _customer(db)
    now = datetime.now(UTC)
    _notification(db, tenant_id=tenant.id, user_id=other.id, channel="email")

    pending = _notification(
        db,
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="RESERVATION_CREATED",
        channel="in_app",
        payload={"public_ref": "R-PENDING"},
    )
    retrying = _notification(
        db,
        tenant_id=other_tenant.id,
        user_id=customer.id,
        kind="RESERVATION_READY",
        payload={"public_ref": "R-RETRY"},
        attempts=1,
        next_attempt_at=now + timedelta(seconds=60),
        error="PushTransientError: network down",
    )
    sent = _notification(
        db,
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="RESERVATION_CONFIRMED",
        channel="email",
        payload={"public_ref": "R-SENT"},
        sent_at=now,
    )
    _notification(
        db,
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="CARD_REQUEST_QUOTED",
        channel="email",
        sent_at=now,
        error="Customer notification preferences disabled",
    )
    _notification(
        db,
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="CARD_REQUEST_DECLINED",
        sent_at=now,
        error="No active push token",
    )
    _notification(
        db,
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="CARD_REQUEST_EXPIRED",
        sent_at=now,
        error="PushTokenInvalid: gone",
    )

    response = client.get("/v1/me/notifications?limit=10", headers=_headers(customer))
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["next_cursor"] is None
    assert len(body["items"]) == 6
    by_kind = {item["kind"]: item for item in body["items"]}
    assert set(by_kind) == {
        "RESERVATION_CREATED",
        "RESERVATION_READY",
        "RESERVATION_CONFIRMED",
        "CARD_REQUEST_QUOTED",
        "CARD_REQUEST_DECLINED",
        "CARD_REQUEST_EXPIRED",
    }

    assert by_kind["RESERVATION_CREATED"]["status"] == "pending"
    assert by_kind["RESERVATION_CREATED"]["channel"] == "in_app"
    assert by_kind["RESERVATION_READY"]["status"] == "retrying"
    assert by_kind["RESERVATION_READY"]["shop"]["slug"] == other_tenant.slug
    assert by_kind["RESERVATION_READY"]["error"] == "PushTransientError: network down"
    assert by_kind["RESERVATION_CONFIRMED"]["status"] == "sent"
    assert by_kind["CARD_REQUEST_QUOTED"]["status"] == "skipped"
    assert by_kind["CARD_REQUEST_DECLINED"]["status"] == "skipped"
    assert by_kind["CARD_REQUEST_EXPIRED"]["status"] == "failed"
    assert by_kind["RESERVATION_READY"]["title"] == "Your cards are ready — R-RETRY"
    assert by_kind["RESERVATION_READY"]["attempts"] == 1
    assert by_kind["RESERVATION_READY"]["next_attempt_at"] is not None

    first_page = client.get("/v1/me/notifications?limit=4", headers=_headers(customer))
    first_body = first_page.json()
    assert len(first_body["items"]) == 4
    assert first_body["next_cursor"] == str(sent.id)

    second_page = client.get(
        f"/v1/me/notifications?limit=4&cursor={first_body['next_cursor']}",
        headers=_headers(customer),
    )
    second_body = second_page.json()
    assert {item["id"] for item in second_body["items"]} == {retrying.id, pending.id}
    assert second_body["next_cursor"] is None


def test_notification_log_returns_empty_and_handles_an_orphan_tenant(client, db):
    customer = _customer(db)
    _notification(db, tenant_id=uuid.uuid4(), user_id=customer.id)

    response = client.get("/v1/me/notifications", headers=_headers(customer))
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}

    empty = client.get("/v1/me/notifications", headers=_headers(_customer(db)))
    assert empty.json() == {"items": [], "next_cursor": None}


def test_notification_log_requires_auth_and_validates_query(client, db):
    assert client.get("/v1/me/notifications").status_code == 401

    customer = _customer(db)
    headers = _headers(customer)
    assert client.get("/v1/me/notifications?cursor=0", headers=headers).status_code == 422
    assert client.get("/v1/me/notifications?limit=0", headers=headers).status_code == 422
    assert client.get("/v1/me/notifications?limit=201", headers=headers).status_code == 422


def test_push_token_list_is_customer_scoped_and_shows_diagnostics(client, db):
    customer = _customer(db)
    other = _customer(db)
    failure_time = datetime.now(UTC)
    active = models.PushToken(
        user_id=customer.id,
        token="active-token-0123456789abcdef",
        token_hash="a" * 64,
        platform="android",
        failure_count=2,
        last_failure_at=failure_time,
        last_error="PushTransientError: network down",
        created_at=failure_time,
    )
    revoked = models.PushToken(
        user_id=customer.id,
        token="revoked-token-0123456789abcdef",
        token_hash="b" * 64,
        platform="ios",
        revoked_at=failure_time,
        failure_count=1,
        last_failure_at=failure_time,
        last_error="PushTokenInvalid: gone",
        created_at=failure_time + timedelta(seconds=1),
    )
    hidden = models.PushToken(
        user_id=other.id,
        token="other-token-0123456789abcdef",
        token_hash="c" * 64,
        platform="android",
    )
    db.add_all([active, revoked, hidden])
    db.commit()

    response = client.get("/v1/me/push-tokens", headers=_headers(customer))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(revoked.id), str(active.id)]
    assert items[0]["revoked_at"] is not None
    assert items[0]["last_error"] == "PushTokenInvalid: gone"
    assert items[1]["failure_count"] == 2
    assert items[1]["last_error"] == "PushTransientError: network down"
    assert "token" not in items[0]

    assert client.get("/v1/me/push-tokens").status_code == 401


def test_notification_rendering_covers_reservation_updates(tenant):
    from app.services import notifications

    row = models.Notification(
        tenant_id=tenant.id,
        user_id=uuid.uuid4(),
        kind="RESERVATION_UPDATED",
        channel="in_app",
        payload={"public_ref": "R-UPDATED", "status": "CONFIRMED"},
    )
    subject, body = notifications.render(row, tenant)
    assert subject == "Reservation R-UPDATED updated"
    assert "Current status: CONFIRMED" in body
