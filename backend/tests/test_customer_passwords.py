from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import models
from app.config import settings
from app.security import derive_otp_code, hash_password
from app.services import notifications
from app.workers import notifications as worker

PASSWORD = "correct-horse-battery"


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.sent.append(
            {
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "headers": headers or {},
            }
        )


def _request(client, path: str, email: str):
    response = client.post(path, json={"email": email})
    assert response.status_code == 202, response.text
    return response


def _challenge(db, email: str, purpose: str) -> models.CustomerOtpChallenge:
    db.expire_all()
    row = db.scalar(
        select(models.CustomerOtpChallenge)
        .where(
            models.CustomerOtpChallenge.email == email,
            models.CustomerOtpChallenge.purpose == purpose,
        )
        .order_by(models.CustomerOtpChallenge.created_at.desc())
        .limit(1)
    )
    assert row is not None
    return row


def _code(challenge: models.CustomerOtpChallenge) -> str:
    return derive_otp_code(challenge.id, challenge.email)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _signup(client, db, email: str = "ana@example.com", password: str = PASSWORD):
    _request(client, "/v1/auth/signup/request", email)
    challenge = _challenge(db, email, "signup")
    response = client.post(
        "/v1/auth/signup/verify",
        json={"email": email, "code": _code(challenge), "password": password},
    )
    assert response.status_code == 200, response.text
    return response, challenge


def _guest_reservation(client, tenant, stock, email: str = "ana@example.com") -> dict:
    response = client.post(
        f"/v1/shops/{tenant.slug}/reservations",
        json={
            "customer": {"name": "Ana Ilic", "email": email, "phone": "+38160111222"},
            "items": [{"stock_id": str(stock.id), "quantity": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _guest_card_request(client, tenant, card, email: str = "ana@example.com") -> dict:
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


def _guest_restock_alert(client, tenant, card, email: str = "ana@example.com") -> dict:
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


def _customer(db, email: str, **kwargs) -> models.User:
    kwargs.setdefault("is_active", True)
    row = models.User(
        tenant_id=None,
        email=email,
        role="customer",
        **kwargs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_signup_creates_a_password_account_and_claims_guest_rows(
    client, db, tenant, other_tenant, card, stock, monkeypatch
):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    monkeypatch.setattr(settings, "otp_debug_code", True)

    reservation = _guest_reservation(client, tenant, stock)
    request = _guest_card_request(client, other_tenant, card)
    alert = _guest_restock_alert(client, tenant, card)

    requested = _request(client, "/v1/auth/signup/request", "Ana@Example.com")
    assert len(requested.json()["debug_code"]) == 6
    challenge = _challenge(db, "ana@example.com", "signup")
    assert challenge.user_id is None
    assert challenge.purpose == "signup"

    sender = RecordingSender()
    assert worker.deliver_otp_challenges(db, sender, now=datetime.now(UTC)) == 1
    assert sender.sent[0]["recipient"] == "ana@example.com"
    assert sender.sent[0]["subject"] == "Verify your Card Tracker email"

    created, _ = _signup(client, db, password=PASSWORD)
    body = created.json()
    assert body["is_new_account"] is True
    assert body["claimed"] == {"reservations": 1, "restock_alerts": 1, "card_requests": 1}
    assert body["customer"]["email"] == "ana@example.com"
    assert body["customer"]["has_password"] is True

    token = body["access_token"]
    me = client.get("/v1/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["has_password"] is True

    db.expire_all()
    customer = db.get(models.User, uuid.UUID(body["customer"]["id"]))
    assert customer is not None and customer.password_hash is not None
    assert db.get(models.Reservation, uuid.UUID(reservation["id"])).customer_id == customer.id
    assert db.get(models.CardRequest, uuid.UUID(request["id"])).customer_id == customer.id
    assert db.get(models.RestockAlert, uuid.UUID(alert["id"])).customer_id == customer.id

    logged_in = client.post(
        "/v1/auth/login",
        json={"email": "ANA@example.com", "password": PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["is_new_account"] is False
    assert logged_in.json()["claimed"] == {
        "reservations": 0,
        "restock_alerts": 0,
        "card_requests": 0,
    }


def test_signup_sets_the_first_password_on_a_legacy_account(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    legacy = _customer(db, "legacy@example.com", email_verified_at=None)

    response, _ = _signup(client, db, "legacy@example.com", PASSWORD)

    body = response.json()
    assert body["is_new_account"] is False
    assert body["customer"]["has_password"] is True
    db.expire_all()
    updated = db.get(models.User, legacy.id)
    assert updated is not None and updated.password_hash is not None
    assert updated.email_verified_at is not None


def test_signup_rejects_a_password_account_inactive_account_and_blank_password(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    _signup(client, db, "taken@example.com", PASSWORD)

    _request(client, "/v1/auth/signup/request", "taken@example.com")
    taken = _challenge(db, "taken@example.com", "signup")
    conflict = client.post(
        "/v1/auth/signup/verify",
        json={"email": "taken@example.com", "code": _code(taken), "password": PASSWORD},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "An account with this email already exists. Sign in instead."

    inactive = _customer(db, "inactive@example.com", is_active=False)
    _request(client, "/v1/auth/signup/request", "inactive@example.com")
    blocked = _challenge(db, "inactive@example.com", "signup")
    unavailable = client.post(
        "/v1/auth/signup/verify",
        json={"email": "inactive@example.com", "code": _code(blocked), "password": PASSWORD},
    )
    assert unavailable.status_code == 403
    assert db.get(models.User, inactive.id).password_hash is None

    _request(client, "/v1/auth/signup/request", "blank@example.com")
    blank = _challenge(db, "blank@example.com", "signup")
    rejected = client.post(
        "/v1/auth/signup/verify",
        json={"email": "blank@example.com", "code": _code(blank), "password": "        "},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "Password cannot be blank."
    # Validation happens before the challenge is consumed.
    assert _challenge(db, "blank@example.com", "signup").consumed_at is None


def test_signup_codes_are_scoped_to_the_signup_purpose(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)

    _request(client, "/v1/auth/signup/request", "ana@example.com")
    signup = _challenge(db, "ana@example.com", "signup")
    login_rejects = client.post(
        "/v1/auth/otp/verify",
        json={"email": "ana@example.com", "code": _code(signup)},
    )
    assert login_rejects.status_code == 401

    _request(client, "/v1/auth/otp/request", "ana@example.com")
    login = _challenge(db, "ana@example.com", "login")
    signup_rejects = client.post(
        "/v1/auth/signup/verify",
        json={"email": "ana@example.com", "code": _code(login), "password": PASSWORD},
    )
    assert signup_rejects.status_code == 401


def test_signup_rejects_expired_and_invalid_codes(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)

    _request(client, "/v1/auth/signup/request", "ana@example.com")
    challenge = _challenge(db, "ana@example.com", "signup")
    actual = _code(challenge)
    wrong = f"{(int(actual) + 1) % 1_000_000:06d}"
    rejected = client.post(
        "/v1/auth/signup/verify",
        json={"email": "ana@example.com", "code": wrong, "password": PASSWORD},
    )
    assert rejected.status_code == 401

    challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    expired = client.post(
        "/v1/auth/signup/verify",
        json={"email": "ana@example.com", "code": actual, "password": PASSWORD},
    )
    assert expired.status_code == 401


def test_password_login_rejects_unknown_inactive_and_passwordless_accounts(client, db):
    unknown = client.post(
        "/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Invalid email or password"

    legacy = _customer(db, "legacy@example.com")
    no_password = client.post(
        "/v1/auth/login",
        json={"email": "legacy@example.com", "password": PASSWORD},
    )
    assert no_password.status_code == 401

    _customer(
        db,
        "inactive@example.com",
        is_active=False,
        password_hash=hash_password(PASSWORD),
        email_verified_at=datetime.now(UTC),
    )
    inactive = client.post(
        "/v1/auth/login",
        json={"email": "inactive@example.com", "password": PASSWORD},
    )
    assert inactive.status_code == 401

    _customer(
        db,
        "unverified@example.com",
        password_hash=hash_password(PASSWORD),
        email_verified_at=None,
    )
    verified = client.post(
        "/v1/auth/login",
        json={"email": "unverified@example.com", "password": PASSWORD},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["customer"]["email_verified_at"] is not None

    wrong = client.post(
        "/v1/auth/login",
        json={"email": legacy.email, "password": "something-else"},
    )
    assert wrong.status_code == 401


def test_password_login_rate_limit_is_shared_per_ip_and_email(client, db, monkeypatch):
    _signup(client, db, "ana@example.com", PASSWORD)

    for _ in range(settings.login_rate_limit):
        attempt = client.post(
            "/v1/auth/login",
            json={"email": "ana@example.com", "password": "wrong-password"},
        )
        assert attempt.status_code == 401

    blocked = client.post(
        "/v1/auth/login",
        json={"email": "ana@example.com", "password": PASSWORD},
    )
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


def test_password_reset_sets_a_new_password_and_revokes_old_sessions(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    monkeypatch.setattr(settings, "otp_debug_code", True)

    created, _ = _signup(client, db, "ana@example.com", PASSWORD)
    old = created.json()
    old_refresh = old["refresh_token"]

    db.expire_all()
    customer = db.get(models.User, uuid.UUID(old["customer"]["id"]))
    assert customer is not None
    customer.email_verified_at = None
    db.commit()

    requested = _request(client, "/v1/auth/password/reset/request", "ana@example.com")
    assert len(requested.json()["debug_code"]) == 6
    challenge = _challenge(db, "ana@example.com", "password_reset")
    assert challenge.purpose == "password_reset"

    sender = RecordingSender()
    assert worker.deliver_otp_challenges(db, sender, now=datetime.now(UTC)) == 1
    assert sender.sent[0]["subject"] == "Reset your Card Tracker password"

    wrong = f"{(int(_code(challenge)) + 1) % 1_000_000:06d}"
    rejected = client.post(
        "/v1/auth/password/reset/verify",
        json={"email": "ana@example.com", "code": wrong, "password": "new-password-123"},
    )
    assert rejected.status_code == 401

    changed = client.post(
        "/v1/auth/password/reset/verify",
        json={
            "email": "ana@example.com",
            "code": _code(challenge),
            "password": "new-password-123",
        },
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["is_new_account"] is False
    assert body["customer"]["has_password"] is True
    assert body["refresh_token"] != old_refresh

    assert client.post("/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 200

    old_password = client.post(
        "/v1/auth/login",
        json={"email": "ana@example.com", "password": PASSWORD},
    )
    assert old_password.status_code == 401
    new_password = client.post(
        "/v1/auth/login",
        json={"email": "ana@example.com", "password": "new-password-123"},
    )
    assert new_password.status_code == 200, new_password.text

    # A second reset exercises the already-verified branch.
    _request(client, "/v1/auth/password/reset/request", "ana@example.com")
    second = _challenge(db, "ana@example.com", "password_reset")
    again = client.post(
        "/v1/auth/password/reset/verify",
        json={
            "email": "ana@example.com",
            "code": _code(second),
            "password": "another-password-123",
        },
    )
    assert again.status_code == 200, again.text

    db.expire_all()
    actions = db.scalars(
        select(models.CustomerAuditEvent.action)
        .where(models.CustomerAuditEvent.user_id == uuid.UUID(body["customer"]["id"]))
        .order_by(models.CustomerAuditEvent.created_at)
    ).all()
    assert "account.password_reset" in actions
    assert "account.sessions_revoked" in actions


def test_password_reset_rejects_unknown_inactive_and_blank_password(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    monkeypatch.setattr(settings, "otp_debug_code", True)

    unknown_request = _request(client, "/v1/auth/password/reset/request", "nobody@example.com")
    unknown = client.post(
        "/v1/auth/password/reset/verify",
        json={
            "email": "nobody@example.com",
            "code": unknown_request.json()["debug_code"],
            "password": "new-password-123",
        },
    )
    assert unknown.status_code == 401

    _customer(
        db,
        "inactive@example.com",
        is_active=False,
        password_hash=hash_password(PASSWORD),
        email_verified_at=None,
    )
    _request(client, "/v1/auth/password/reset/request", "inactive@example.com")
    blocked = _challenge(db, "inactive@example.com", "password_reset")
    unavailable = client.post(
        "/v1/auth/password/reset/verify",
        json={
            "email": "inactive@example.com",
            "code": _code(blocked),
            "password": "new-password-123",
        },
    )
    assert unavailable.status_code == 403

    _request(client, "/v1/auth/password/reset/request", "blank@example.com")
    blank = _challenge(db, "blank@example.com", "password_reset")
    rejected = client.post(
        "/v1/auth/password/reset/verify",
        json={"email": "blank@example.com", "code": _code(blank), "password": "        "},
    )
    assert rejected.status_code == 400


def test_change_password_requires_the_current_password_and_rotates_the_session(client, db, monkeypatch):
    created, _ = _signup(client, db, "ana@example.com", PASSWORD)
    body = created.json()
    headers = _headers(body["access_token"])
    old_refresh = body["refresh_token"]

    db.expire_all()
    customer = db.get(models.User, uuid.UUID(body["customer"]["id"]))
    assert customer is not None
    customer.email_verified_at = None
    db.commit()

    wrong = client.post(
        "/v1/me/password",
        headers=headers,
        json={"current_password": "not-the-password", "new_password": "new-password-123"},
    )
    assert wrong.status_code == 403

    missing = client.post(
        "/v1/me/password",
        headers=headers,
        json={"new_password": "new-password-123"},
    )
    assert missing.status_code == 403

    blank = client.post(
        "/v1/me/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "        "},
    )
    assert blank.status_code == 400

    changed = client.post(
        "/v1/me/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "new-password-123"},
    )
    assert changed.status_code == 200, changed.text
    updated = changed.json()
    assert updated["customer"]["has_password"] is True
    assert updated["refresh_token"] != old_refresh
    assert client.post("/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401

    old_password = client.post(
        "/v1/auth/login",
        json={"email": "ana@example.com", "password": PASSWORD},
    )
    assert old_password.status_code == 401
    new_password = client.post(
        "/v1/auth/login",
        json={"email": "ana@example.com", "password": "new-password-123"},
    )
    assert new_password.status_code == 200

    db.expire_all()
    actions = db.scalars(
        select(models.CustomerAuditEvent.action)
        .where(models.CustomerAuditEvent.user_id == uuid.UUID(body["customer"]["id"]))
        .order_by(models.CustomerAuditEvent.created_at)
    ).all()
    assert "account.password_changed" in actions


def test_change_password_sets_the_first_password_on_a_legacy_session(client, db, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    _request(client, "/v1/auth/otp/request", "legacy@example.com")
    challenge = _challenge(db, "legacy@example.com", "login")
    signed_in = client.post(
        "/v1/auth/otp/verify",
        json={"email": "legacy@example.com", "code": _code(challenge)},
    )
    assert signed_in.status_code == 200, signed_in.text
    body = signed_in.json()
    assert body["customer"]["has_password"] is False

    changed = client.post(
        "/v1/me/password",
        headers=_headers(body["access_token"]),
        json={"new_password": "legacy-password-123"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["customer"]["has_password"] is True


def test_change_password_is_rate_limited(client, db, monkeypatch):
    created, _ = _signup(client, db, "ana@example.com", PASSWORD)
    headers = _headers(created.json()["access_token"])

    monkeypatch.setattr(settings, "login_rate_limit", 1)
    first = client.post(
        "/v1/me/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "new-password-123"},
    )
    assert first.status_code == 200, first.text
    blocked = client.post(
        "/v1/me/password",
        headers=headers,
        json={"new_password": "another-password-123"},
    )
    assert blocked.status_code == 429


def test_otp_renderers_choose_copy_by_purpose():
    assert notifications.render_otp_for_purpose("signup", "123456", 60)[0] == ("Verify your Card Tracker email")
    assert notifications.render_otp_for_purpose("password_reset", "123456", 60)[0] == (
        "Reset your Card Tracker password"
    )
    assert notifications.render_otp_for_purpose("email_change", "123456", 60)[0] == (
        "Confirm your new Card Tracker email"
    )
    assert notifications.render_otp_for_purpose("login", "123456", 60)[0] == ("Your Card Tracker sign-in code")
    assert notifications.render_otp_for_purpose("unknown", "123456", 60)[0] == ("Your Card Tracker sign-in code")
