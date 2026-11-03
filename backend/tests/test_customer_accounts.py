from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.security import derive_otp_code
from app.workers import notifications as worker


class RecordingSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self.error = error

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(
            {
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "headers": headers or {},
            }
        )


def _request_code(client, email: str = "ana@example.com"):
    response = client.post("/v1/auth/otp/request", json={"email": email})
    assert response.status_code == 202, response.text
    return response


def _latest_challenge(db, email: str = "ana@example.com") -> models.CustomerOtpChallenge:
    db.expire_all()
    challenge = db.scalar(
        select(models.CustomerOtpChallenge)
        .where(models.CustomerOtpChallenge.email == email)
        .order_by(models.CustomerOtpChallenge.created_at.desc())
        .limit(1)
    )
    assert challenge is not None
    return challenge


def _verify(client, db, email: str = "ana@example.com", code: str | None = None):
    challenge = _latest_challenge(db, email)
    if code is None:
        code = derive_otp_code(challenge.id, email)
    return client.post("/v1/auth/otp/verify", json={"email": email, "code": code})


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _guest_reservation(client, tenant, stock, email: str = "Ana@Example.com") -> dict:
    response = client.post(
        f"/v1/shops/{tenant.slug}/reservations",
        json={
            "customer": {"name": "Ana Ilic", "email": email, "phone": "+38160111222"},
            "items": [{"stock_id": str(stock.id), "quantity": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _guest_card_request(client, tenant, card, email: str = "Ana@Example.com") -> dict:
    response = client.post(
        f"/v1/shops/{tenant.slug}/card-requests",
        json={
            "customer": {"name": "Ana Ilic", "email": email, "phone": "+38160111222"},
            "card_id": str(card.id),
            "quantity": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _guest_restock_alert(client, tenant, card, email: str = "Ana@Example.com") -> dict:
    response = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json={
            "email": email,
            "name": "Ana",
            "card_id": str(card.id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_otp_request_is_generic_and_stores_no_code(client, db):
    response = _request_code(client, "Ana@Example.com")

    body = response.json()
    assert body == {"expires_in": 600, "resend_after": 60, "debug_code": None}
    assert response.headers["cache-control"] == "no-store"

    challenge = _latest_challenge(db)
    assert challenge.email == "ana@example.com"
    assert challenge.consumed_at is None
    assert challenge.email_sent_at is None
    assert not hasattr(challenge, "code")


def test_request_cooldown_and_new_code_invalidates_the_old_one(client, db):
    _request_code(client)
    first = _latest_challenge(db)
    first_code = derive_otp_code(first.id, first.email)

    too_soon = client.post("/v1/auth/otp/request", json={"email": "ana@example.com"})
    assert too_soon.status_code == 429
    assert "retry-after" in too_soon.headers

    # Simulate that enough time passed without weakening the production rule.
    first.created_at = datetime.now(UTC) - timedelta(seconds=settings.otp_resend_seconds + 1)
    db.commit()
    _request_code(client)
    second = _latest_challenge(db)
    assert second.id != first.id

    old = client.post("/v1/auth/otp/verify", json={"email": "ana@example.com", "code": first_code})
    assert old.status_code == 401


def test_verify_creates_a_global_account_and_claims_guest_rows(
    client, db, tenant, other_tenant, card, stock, monkeypatch
):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    reservation = _guest_reservation(client, tenant, stock)
    request = _guest_card_request(client, other_tenant, card)
    alert = _guest_restock_alert(client, tenant, card)
    unclaimed = _guest_reservation(client, tenant, stock, email="someone-else@example.com")

    _request_code(client)
    verified = _verify(client, db)

    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["is_new_account"] is True
    assert body["expires_in"] == 43200
    assert body["customer"]["email"] == "ana@example.com"
    assert body["claimed"] == {"reservations": 1, "restock_alerts": 1, "card_requests": 1}
    token = body["access_token"]

    me = client.get("/v1/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["id"] == body["customer"]["id"]
    assert me.headers["cache-control"] == "no-store"

    reservations = client.get("/v1/me/reservations", headers=_headers(token)).json()["items"]
    assert [row["id"] for row in reservations] == [reservation["id"]]
    assert reservations[0]["shop"] == {"slug": tenant.slug, "name": tenant.name}
    assert reservations[0]["line_count"] == 1

    detail = client.get(f"/v1/me/reservations/{reservation['id']}", headers=_headers(token))
    assert detail.status_code == 200
    assert detail.json()["lines"][0]["quantity"] == 1
    assert detail.json()["access_token"] is None

    requests = client.get("/v1/me/card-requests", headers=_headers(token)).json()["items"]
    assert [row["id"] for row in requests] == [request["id"]]
    assert requests[0]["shop"]["slug"] == other_tenant.slug

    alerts = client.get("/v1/me/restock-alerts", headers=_headers(token)).json()["items"]
    assert [row["id"] for row in alerts] == [alert["id"]]
    assert alerts[0]["card_name"] == card.name
    assert alerts[0]["shop"]["slug"] == tenant.slug

    db.expire_all()
    assert db.get(models.Reservation, uuid.UUID(reservation["id"])).customer_id is not None
    assert db.get(models.Reservation, uuid.UUID(unclaimed["id"])).customer_id is None
    assert db.scalar(select(func.count()).select_from(models.User).where(models.User.role == "customer")) == 1

    # Case-insensitive identity and idempotent claiming.
    _request_code(client, "ANA@EXAMPLE.COM")
    again = _verify(client, db, "ana@example.com")
    assert again.status_code == 200
    assert again.json()["is_new_account"] is False
    assert again.json()["claimed"] == {"reservations": 0, "restock_alerts": 0, "card_requests": 0}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(models.User).where(models.User.role == "customer")) == 1


def test_claim_never_overwrites_another_account(client, db, tenant, stock):
    other = models.User(
        tenant_id=None,
        email="ana@example.com",
        role="customer",
        is_active=True,
    )
    db.add(other)
    db.flush()
    owned = models.Reservation(
        tenant_id=tenant.id,
        public_ref="R-OWNED1",
        customer_id=other.id,
        customer_name="Existing",
        email="ana@example.com",
        phone="",
        note="",
        status="REQUESTED",
        total_minor=0,
        currency="RSD",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        source="app",
    )
    db.add(owned)
    db.commit()

    guest = _guest_reservation(client, tenant, stock)
    _request_code(client)
    verified = _verify(client, db)
    assert verified.status_code == 200
    assert verified.json()["claimed"]["reservations"] == 1

    db.expire_all()
    assert db.get(models.Reservation, owned.id).customer_id == other.id
    assert db.get(models.Reservation, uuid.UUID(guest["id"])).customer_id == uuid.UUID(
        verified.json()["customer"]["id"]
    )


def test_wrong_code_attempts_are_bounded(client, db):
    _request_code(client)
    challenge = _latest_challenge(db)
    actual = derive_otp_code(challenge.id, challenge.email)
    wrong = f"{(int(actual) + 1) % 1_000_000:06d}"

    for _ in range(settings.otp_max_attempts):
        response = client.post("/v1/auth/otp/verify", json={"email": "ana@example.com", "code": wrong})
        assert response.status_code == 401

    db.expire_all()
    challenge = _latest_challenge(db)
    assert challenge.attempts == settings.otp_max_attempts
    assert challenge.consumed_at is not None

    correct = client.post(
        "/v1/auth/otp/verify",
        json={"email": "ana@example.com", "code": actual},
    )
    assert correct.status_code == 401


def test_signed_in_creates_attach_customer_and_use_account_email(client, db, tenant, card, stock):
    _request_code(client)
    verified = _verify(client, db)
    token = verified.json()["access_token"]
    customer = verified.json()["customer"]

    reservation = client.post(
        f"/v1/shops/{tenant.slug}/reservations",
        headers=_headers(token),
        json={
            "customer": {"name": "Ana", "email": "someone-else@example.com", "phone": ""},
            "items": [{"stock_id": str(stock.id), "quantity": 1}],
        },
    )
    assert reservation.status_code == 201, reservation.text
    reservation_body = reservation.json()
    assert reservation_body["access_token"]

    # The unchanged guest-token endpoint still works for the signed-in create.
    fetched = client.get(
        f"/v1/reservations/{reservation_body['id']}",
        headers={"X-Shop-Slug": tenant.slug, "X-Reservation-Token": reservation_body["access_token"]},
    )
    assert fetched.status_code == 200

    request = client.post(
        f"/v1/shops/{tenant.slug}/card-requests",
        headers=_headers(token),
        json={
            "customer": {"name": "Ana", "email": "someone-else@example.com"},
            "card_id": str(card.id),
            "quantity": 1,
        },
    )
    assert request.status_code == 201, request.text

    alert = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        headers=_headers(token),
        json={
            "email": "someone-else@example.com",
            "card_id": str(card.id),
            "finish": "foil",
            "condition": "NM",
            "language": "en",
        },
    )
    assert alert.status_code == 201, alert.text

    db.expire_all()
    customer_id = uuid.UUID(customer["id"])
    reservation_row = db.get(models.Reservation, uuid.UUID(reservation_body["id"]))
    request_row = db.get(models.CardRequest, uuid.UUID(request.json()["id"]))
    alert_row = db.get(models.RestockAlert, uuid.UUID(alert.json()["id"]))
    assert reservation_row.customer_id == customer_id
    assert request_row.customer_id == customer_id
    assert alert_row.customer_id == customer_id
    assert reservation_row.email == "ana@example.com"
    assert request_row.email == "ana@example.com"
    assert alert_row.email == "ana@example.com"

    guest = _guest_reservation(client, tenant, stock, email="guest@example.com")
    db.expire_all()
    assert db.get(models.Reservation, uuid.UUID(guest["id"])).customer_id is None


def test_account_actions_and_token_boundaries(client, db, tenant, card, stock, auth):
    reservation = _guest_reservation(client, tenant, stock)
    request = _guest_card_request(client, tenant, card)
    alert = _guest_restock_alert(client, tenant, card)

    _request_code(client)
    token = _verify(client, db).json()["access_token"]
    headers = _headers(token)

    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers=auth).status_code == 401
    assert client.get("/v1/staff/me", headers=headers).status_code == 401

    cancelled = client.post(f"/v1/me/reservations/{reservation['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"

    quote = client.post(
        f"/v1/staff/card-requests/{request['id']}/quote",
        headers=auth,
        json={"quote_price_minor": 1000, "vendor_note": "Ready"},
    )
    assert quote.status_code == 200, quote.text
    accepted = client.post(f"/v1/me/card-requests/{request['id']}/accept", headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ACCEPTED"
    assert accepted.json()["shop"]["slug"] == tenant.slug

    cancelled_request = client.post(f"/v1/me/card-requests/{request['id']}/cancel", headers=headers)
    assert cancelled_request.status_code == 200
    assert cancelled_request.json()["status"] == "CANCELLED"

    deleted = client.delete(f"/v1/me/restock-alerts/{alert['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/v1/me/restock-alerts", headers=headers).json()["items"] == []


def test_refresh_tokens_rotate_and_logout_revokes_all_sessions(client, db):
    _request_code(client)
    verified = _verify(client, db)
    assert verified.status_code == 200, verified.text
    first = verified.json()
    old_access = first["access_token"]
    old_refresh = first["refresh_token"]

    rotated = client.post("/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200, rotated.text
    rotated_body = rotated.json()
    assert rotated_body["access_token"]
    assert rotated_body["refresh_token"] != old_refresh
    assert rotated_body["refresh_expires_in"] == 604800

    logout = client.post("/v1/auth/logout", headers=_headers(old_access))
    assert logout.status_code == 204, logout.text

    revoked = client.post("/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Refresh token expired"

    newest = client.post("/v1/auth/refresh", json={"refresh_token": rotated_body["refresh_token"]})
    assert newest.status_code == 401
    assert newest.json()["detail"] == "Refresh token expired"


def test_customer_notification_preferences_block_delivery(client, db, tenant):
    _request_code(client)
    verified = _verify(client, db)
    body = verified.json()
    customer = db.get(models.User, uuid.UUID(body["customer"]["id"]))
    customer.email_notifications_enabled = False
    customer.push_notifications_enabled = False
    customer.quiet_hours_enabled = True
    customer.notifications_opt_out = True
    db.commit()

    email_row = models.Notification(
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="RESERVATION_READY",
        payload={"public_ref": "R-ABC123", "shop_slug": tenant.slug},
        channel="email",
        recipient=customer.email,
    )
    push_row = models.Notification(
        tenant_id=tenant.id,
        user_id=customer.id,
        kind="RESERVATION_READY",
        payload={"public_ref": "R-ABC123", "shop_slug": tenant.slug},
        channel="push",
    )
    db.add_all([email_row, push_row])
    db.commit()

    delivered_email = worker.deliver_tenant(db, tenant, RecordingSender(), now=datetime.now(UTC))
    assert delivered_email == 0
    assert email_row.sent_at is not None
    assert email_row.error == "Customer notification preferences disabled"

    class FakePushSender:
        def send(self, *, token, platform, title, body, url):
            raise AssertionError("push should be skipped when preferences are disabled")

    delivered_push = worker.deliver_push(db, tenant, FakePushSender(), now=datetime.now(UTC))
    assert delivered_push == 0
    assert push_row.sent_at is not None
    assert push_row.error == "Customer notification preferences disabled"


def test_inactive_account_is_rejected_after_a_valid_code(client, db):
    inactive = models.User(
        tenant_id=None,
        email="ana@example.com",
        role="customer",
        is_active=False,
        email_verified_at=datetime.now(UTC),
    )
    db.add(inactive)
    db.commit()

    _request_code(client)
    response = _verify(client, db)
    assert response.status_code == 403
    assert response.json()["detail"] == "This account is unavailable."

    db.expire_all()
    challenge = _latest_challenge(db)
    assert challenge.consumed_at is not None


def test_worker_delivers_otp_and_retries_without_logging_the_code(client, db, monkeypatch):
    _request_code(client)
    challenge = _latest_challenge(db)
    code = derive_otp_code(challenge.id, challenge.email)
    now = datetime.now(UTC)

    failing = RecordingSender(RuntimeError("smtp down"))
    assert worker.deliver_otp_challenges(db, failing, now=now) == 0
    db.refresh(challenge)
    assert challenge.email_attempts == 1
    assert challenge.email_sent_at is None
    assert challenge.email_error == "RuntimeError: delivery failed"
    assert challenge.next_email_attempt_at is not None

    assert worker.deliver_otp_challenges(db, RecordingSender(), now=now + timedelta(seconds=30)) == 0
    sender = RecordingSender()
    assert worker.deliver_otp_challenges(db, sender, now=now + timedelta(seconds=61)) == 1
    assert sender.sent[0]["recipient"] == "ana@example.com"
    assert code in sender.sent[0]["body"]
    assert code not in sender.sent[0]["subject"]

    db.refresh(challenge)
    assert challenge.email_sent_at is not None
    assert challenge.email_error is None

    # Consumed challenges are never sent.
    challenge.consumed_at = datetime.now(UTC)
    db.commit()
    again = RecordingSender()
    assert worker.deliver_otp_challenges(db, again, now=now + timedelta(days=1)) == 0
    assert again.sent == []


def test_run_once_drains_otp_and_tenant_notifications(db, tenant, client, monkeypatch):
    _request_code(client)
    note = models.Notification(
        tenant_id=tenant.id,
        kind="RESERVATION_READY",
        payload={"public_ref": "R-ABC123"},
        channel="email",
        recipient="ana@example.com",
    )
    db.add(note)
    db.commit()

    maker = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", maker)

    sender = RecordingSender()
    assert worker.run_once(sender=sender) == 2
    recipients = {item["recipient"] for item in sender.sent}
    assert recipients == {"ana@example.com"}
    subjects = {item["subject"] for item in sender.sent}
    assert "Your Card Tracker sign-in code" in subjects
    assert "Your cards are ready — R-ABC123" in subjects
