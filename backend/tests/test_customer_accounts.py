from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.security import derive_otp_code
from app.services import accounts
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


def test_logout_with_refresh_token_revokes_only_that_device(client, db):
    _request_code(client)
    verified = _verify(client, db)
    assert verified.status_code == 200, verified.text
    body = verified.json()
    customer_id = uuid.UUID(body["customer"]["id"])

    other_refresh = "o" * 32
    db.add(
        models.CustomerRefreshToken(
            user_id=customer_id,
            token_hash=accounts._refresh_token_hash(other_refresh),
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.commit()

    logout = client.post(
        "/v1/auth/logout",
        headers=_headers(body["access_token"]),
        json={"refresh_token": body["refresh_token"]},
    )
    assert logout.status_code == 204, logout.text

    assert client.post("/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401
    still_active = client.post("/v1/auth/refresh", json={"refresh_token": other_refresh})
    assert still_active.status_code == 200, still_active.text

    db.expire_all()
    event = db.scalar(
        select(models.CustomerAuditEvent).where(
            models.CustomerAuditEvent.user_id == customer_id,
            models.CustomerAuditEvent.action == "account.logout",
        )
    )
    assert event is not None
    assert event.data == {"token_count": 1, "single_token": True}


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
        def send(
            self,
            *,
            token: str,
            platform: str,
            title: str,
            body: str,
            url: str | None = None,
        ) -> None:
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


def _audit_actions(db, customer_id):
    db.expire_all()
    return [
        row.action
        for row in db.scalars(
            select(models.CustomerAuditEvent)
            .where(models.CustomerAuditEvent.user_id == customer_id)
            .order_by(models.CustomerAuditEvent.id)
        ).all()
    ]


def test_email_change_verifies_the_new_address_and_claims_its_guest_rows(client, db, tenant, stock, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    monkeypatch.setattr(settings, "otp_debug_code", True)

    guest = _guest_reservation(client, tenant, stock, email="new@example.com")

    _request_code(client)
    signed_in = _verify(client, db)
    assert signed_in.status_code == 200, signed_in.text
    body = signed_in.json()
    headers = _headers(body["access_token"])
    customer_id = uuid.UUID(body["customer"]["id"])
    old_refresh = body["refresh_token"]

    same = client.post("/v1/me/email", headers=headers, json={"email": "ana@example.com"})
    assert same.status_code == 400
    assert same.json()["detail"] == "This is already your email address."

    taken = models.User(
        tenant_id=None,
        email="taken@example.com",
        role="customer",
        is_active=True,
    )
    db.add(taken)
    db.commit()
    unavailable = client.post("/v1/me/email", headers=headers, json={"email": "taken@example.com"})
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"] == "This email address is already in use."

    requested = client.post("/v1/me/email", headers=headers, json={"email": "New@Example.com"})
    assert requested.status_code == 202, requested.text
    assert len(requested.json()["debug_code"]) == 6

    # A second request with the cooldown disabled replaces the pending code.
    replacement = client.post("/v1/me/email", headers=headers, json={"email": "new@example.com"})
    assert replacement.status_code == 202, replacement.text

    challenge = _latest_challenge(db, "new@example.com")
    assert challenge.user_id == customer_id
    assert challenge.consumed_at is None

    sender = RecordingSender()
    assert worker.deliver_otp_challenges(db, sender, now=datetime.now(UTC)) == 1
    assert sender.sent[0]["recipient"] == "new@example.com"
    assert sender.sent[0]["subject"] == "Confirm your new Card Tracker email"

    actual = derive_otp_code(challenge.id, challenge.email)
    wrong = f"{(int(actual) + 1) % 1_000_000:06d}"
    rejected = client.post(
        "/v1/me/email/verify",
        headers=headers,
        json={"email": "new@example.com", "code": wrong},
    )
    assert rejected.status_code == 401

    changed = client.post(
        "/v1/me/email/verify",
        headers=headers,
        json={"email": "new@example.com", "code": actual},
    )
    assert changed.status_code == 200, changed.text
    changed_body = changed.json()
    assert changed_body["customer"]["email"] == "new@example.com"
    assert changed_body["customer"]["email_verified_at"] is not None
    assert changed_body["is_new_account"] is False
    assert changed_body["claimed"] == {"reservations": 1, "restock_alerts": 0, "card_requests": 0}
    assert changed_body["refresh_token"] != old_refresh

    stale = client.post("/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert stale.status_code == 401

    me = client.get("/v1/me", headers=_headers(changed_body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"

    db.expire_all()
    assert db.get(models.User, customer_id).email == "new@example.com"
    assert db.get(models.Reservation, uuid.UUID(guest["id"])).customer_id == customer_id
    actions = _audit_actions(db, customer_id)
    assert actions[0] == "account.login"
    assert "account.sessions_revoked" in actions
    assert actions[-1] == "account.email_changed"


def test_email_change_rejects_expired_attempts_and_late_conflicts(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)

    _request_code(client)
    signed_in = _verify(client, db)
    headers = _headers(signed_in.json()["access_token"])

    missing = client.post(
        "/v1/me/email/verify",
        headers=headers,
        json={"email": "other@example.com", "code": "123456"},
    )
    assert missing.status_code == 401

    requested = client.post("/v1/me/email", headers=headers, json={"email": "free@example.com"})
    assert requested.status_code == 202
    challenge = _latest_challenge(db, "free@example.com")
    actual = derive_otp_code(challenge.id, challenge.email)
    wrong = f"{(int(actual) + 1) % 1_000_000:06d}"
    for _ in range(settings.otp_max_attempts):
        response = client.post(
            "/v1/me/email/verify",
            headers=headers,
            json={"email": "free@example.com", "code": wrong},
        )
        assert response.status_code == 401

    db.expire_all()
    challenged = _latest_challenge(db, "free@example.com")
    assert challenged.attempts == settings.otp_max_attempts
    assert challenged.consumed_at is not None

    again = client.post("/v1/me/email", headers=headers, json={"email": "free@example.com"})
    assert again.status_code == 202
    expired = _latest_challenge(db, "free@example.com")
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    late = client.post(
        "/v1/me/email/verify",
        headers=headers,
        json={"email": "free@example.com", "code": derive_otp_code(expired.id, expired.email)},
    )
    assert late.status_code == 401

    third = client.post("/v1/me/email", headers=headers, json={"email": "free@example.com"})
    assert third.status_code == 202
    final = _latest_challenge(db, "free@example.com")
    db.add(
        models.User(
            tenant_id=None,
            email="free@example.com",
            role="customer",
            is_active=True,
        )
    )
    db.commit()
    conflict = client.post(
        "/v1/me/email/verify",
        headers=headers,
        json={"email": "free@example.com", "code": derive_otp_code(final.id, final.email)},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "This email address is already in use."
    db.expire_all()
    assert db.get(models.User, uuid.UUID(signed_in.json()["customer"]["id"])).email == "ana@example.com"


def test_email_change_request_respects_the_resend_cooldown(client, db):
    _request_code(client)
    signed_in = _verify(client, db)
    headers = _headers(signed_in.json()["access_token"])

    first = client.post("/v1/me/email", headers=headers, json={"email": "cool@example.com"})
    assert first.status_code == 202
    too_soon = client.post("/v1/me/email", headers=headers, json={"email": "cool@example.com"})
    assert too_soon.status_code == 429
    assert "retry-after" in too_soon.headers


def test_login_and_email_change_challenges_are_independent(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)

    _request_code(client)
    signed_in = _verify(client, db)
    headers = _headers(signed_in.json()["access_token"])
    customer_id = uuid.UUID(signed_in.json()["customer"]["id"])
    target = "new@example.com"

    _request_code(client, target)
    login_challenge = _latest_challenge(db, target)
    assert login_challenge.user_id is None

    requested = client.post("/v1/me/email", headers=headers, json={"email": target})
    assert requested.status_code == 202
    change_challenge = _latest_challenge(db, target)
    assert change_challenge.user_id == customer_id
    assert change_challenge.id != login_challenge.id

    # A fresh login request replaces only the login challenge.
    _request_code(client, target)
    db.expire_all()
    still_pending = db.get(models.CustomerOtpChallenge, change_challenge.id)
    consumed_login = db.get(models.CustomerOtpChallenge, login_challenge.id)
    assert still_pending is not None and still_pending.consumed_at is None
    assert consumed_login is not None and consumed_login.consumed_at is not None
    new_login = _latest_challenge(db, target)
    assert new_login.user_id is None

    # The login endpoint must not accept the email-change code.
    change_code = derive_otp_code(change_challenge.id, target)
    rejected = client.post("/v1/auth/otp/verify", json={"email": target, "code": change_code})
    assert rejected.status_code == 401

    login_code = derive_otp_code(new_login.id, target)
    logged_in = client.post("/v1/auth/otp/verify", json={"email": target, "code": login_code})
    assert logged_in.status_code == 200, logged_in.text


def test_customer_audit_covers_profile_refresh_and_session_actions(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)

    _request_code(client)
    signed_in = _verify(client, db)
    body = signed_in.json()
    headers = _headers(body["access_token"])
    refresh_token = body["refresh_token"]
    customer_id = uuid.UUID(body["customer"]["id"])
    db.expire_all()
    assert _audit_actions(db, customer_id) == ["account.login"]

    empty = client.patch("/v1/me", headers=headers, json={})
    assert empty.status_code == 200
    db.expire_all()
    assert _audit_actions(db, customer_id) == ["account.login"]

    updated = client.patch(
        "/v1/me",
        headers=headers,
        json={
            "display_name": " Ana ",
            "phone": " +381600000000 ",
            "push_notifications_enabled": False,
            "email_notifications_enabled": False,
            "quiet_hours_enabled": True,
            "notifications_opt_out": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Ana"
    db.expire_all()
    profile = db.scalar(
        select(models.CustomerAuditEvent).where(
            models.CustomerAuditEvent.user_id == customer_id,
            models.CustomerAuditEvent.action == "account.profile_updated",
        )
    )
    assert profile is not None
    assert profile.data["fields"] == [
        "display_name",
        "phone",
        "push_notifications_enabled",
        "email_notifications_enabled",
        "quiet_hours_enabled",
        "notifications_opt_out",
    ]

    rotated = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200, rotated.text
    rotated_body = rotated.json()

    revoked = client.post("/v1/me/sessions/revoke-all", headers=_headers(rotated_body["access_token"]))
    assert revoked.status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": rotated_body["refresh_token"]}).status_code == 401

    _request_code(client)
    second = _verify(client, db).json()
    logout = client.post("/v1/auth/logout", headers=_headers(second["access_token"]))
    assert logout.status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401

    db.expire_all()
    actions = _audit_actions(db, customer_id)
    assert "account.profile_updated" in actions
    assert "account.session_refreshed" in actions
    assert actions.count("account.sessions_revoked") == 1
    assert actions.count("account.logout") == 1


def test_delete_account_revokes_sessions_and_records_audit(client, db):
    _request_code(client)
    signed_in = _verify(client, db)
    body = signed_in.json()
    customer_id = uuid.UUID(body["customer"]["id"])

    deleted = client.delete("/v1/me", headers=_headers(body["access_token"]))
    assert deleted.status_code == 204
    assert client.get("/v1/me", headers=_headers(body["access_token"])).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401

    db.expire_all()
    assert db.get(models.User, customer_id).is_active is False
    actions = _audit_actions(db, customer_id)
    assert "account.sessions_revoked" in actions
    assert actions[-1] == "account.deleted"


def test_refresh_rejects_unknown_tokens_and_non_customer_rows(client, db, tenant):
    _request_code(client)
    signed_in = _verify(client, db)
    body = signed_in.json()
    customer_id = uuid.UUID(body["customer"]["id"])

    unknown = client.post("/v1/auth/refresh", json={"refresh_token": "x" * 32})
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Invalid refresh token"

    staff = models.User(
        tenant_id=tenant.id,
        email="staff@example.com",
        role="staff",
        is_active=True,
    )
    db.add(staff)
    db.flush()
    staff_token = "s" * 32
    db.add(
        models.CustomerRefreshToken(
            user_id=staff.id,
            token_hash=accounts._refresh_token_hash(staff_token),
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.commit()

    wrong_owner = client.post("/v1/auth/refresh", json={"refresh_token": staff_token})
    assert wrong_owner.status_code == 401
    assert wrong_owner.json()["detail"] == "Invalid customer session"

    # A targeted revoke leaves the other token active and records the action.
    other = "o" * 32
    db.add(
        models.CustomerRefreshToken(
            user_id=customer_id,
            token_hash=accounts._refresh_token_hash(other),
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.commit()
    accounts.revoke_customer_refresh_tokens(
        db,
        customer_id,
        body["refresh_token"],
        action="account.logout",
        commit=False,
    )
    db.commit()
    db.expire_all()
    rows = db.scalars(
        select(models.CustomerRefreshToken).where(models.CustomerRefreshToken.user_id == customer_id)
    ).all()
    assert sum(1 for row in rows if row.revoked_at is not None) == 1
    assert sum(1 for row in rows if row.revoked_at is None) == 1
    event = db.scalar(
        select(models.CustomerAuditEvent).where(
            models.CustomerAuditEvent.user_id == customer_id, models.CustomerAuditEvent.action == "account.logout"
        )
    )
    assert event is not None
    assert event.data == {"token_count": 1, "single_token": True}


def test_notification_allowed_rejects_inactive_unknown_and_disabled_channels(db):
    assert worker.customer_notification_allowed(db, user_id=None, channel="email") is True

    unknown = worker.customer_notification_allowed(db, user_id=uuid.uuid4(), channel="email")
    assert unknown is False

    disabled = models.User(
        tenant_id=None,
        email="disabled@example.com",
        role="customer",
        is_active=False,
    )
    email_off = models.User(
        tenant_id=None,
        email="email-off@example.com",
        role="customer",
        is_active=True,
        email_notifications_enabled=False,
    )
    push_off = models.User(
        tenant_id=None,
        email="push-off@example.com",
        role="customer",
        is_active=True,
        push_notifications_enabled=False,
    )
    db.add_all([disabled, email_off, push_off])
    db.commit()

    assert worker.customer_notification_allowed(db, user_id=disabled.id, channel="email") is False
    assert worker.customer_notification_allowed(db, user_id=email_off.id, channel="email") is False
    assert worker.customer_notification_allowed(db, user_id=push_off.id, channel="push") is False


def test_app_card_url_custom_scheme_and_scheme_less_public_url(tenant, monkeypatch):
    from app.services import notifications

    monkeypatch.setattr(settings, "public_app_url", "")
    assert notifications.app_card_url(tenant, {}) == f"cardtracker://shop/{tenant.slug}"
    assert notifications.app_card_url(tenant, {"stock_id": "s1"}) == f"cardtracker://shop/{tenant.slug}/card/s1"

    monkeypatch.setattr(settings, "public_app_url", "app.example.test/")
    assert (
        notifications.app_card_url(tenant, {"stock_id": "s1"}) == f"https://app.example.test/shop/{tenant.slug}/card/s1"
    )
