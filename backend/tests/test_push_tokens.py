from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import models
from app.security import create_customer_access_token


def _customer(db, email: str = "push@example.com") -> models.User:
    user = models.User(
        tenant_id=None,
        email=email,
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


def _register(client, user: models.User, token: str = "fcm-token-0123456789abcdef", platform: str = "android"):
    return client.post(
        "/v1/me/push-tokens",
        json={"token": token, "platform": platform},
        headers=_headers(user),
    )


def test_register_and_refresh_push_token(client, db):
    user = _customer(db)
    token = "fcm-token-0123456789abcdef"

    created = _register(client, user, token)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["platform"] == "android"
    assert "token" not in body

    db.expire_all()
    row = db.scalar(select(models.PushToken).where(models.PushToken.user_id == user.id))
    assert row is not None
    assert row.token == token
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.revoked_at is None
    row.last_seen_at = datetime(2020, 1, 1, tzinfo=UTC)
    db.commit()

    refreshed = _register(client, user, token, platform="ios")
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["id"] == body["id"]
    assert refreshed.json()["platform"] == "ios"

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(models.PushToken)) == 1
    row = db.get(models.PushToken, uuid.UUID(body["id"]))
    assert row is not None
    last_seen = row.last_seen_at if row.last_seen_at.tzinfo else row.last_seen_at.replace(tzinfo=UTC)
    assert last_seen > datetime(2020, 1, 1, tzinfo=UTC)


def test_register_rejects_a_token_owned_by_another_customer(client, db):
    first = _customer(db, "first@example.com")
    second = _customer(db, "second@example.com")
    token = "apns-token-0123456789abcdef"

    assert _register(client, first, token, platform="ios").status_code == 201

    conflict = _register(client, second, token, platform="ios")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "This device token is registered to another account."


def test_unregister_is_idempotent_and_allows_re_registration(client, db):
    user = _customer(db)
    token = "fcm-token-0123456789abcdef"
    created = _register(client, user, token)
    assert created.status_code == 201

    first = client.delete(f"/v1/me/push-tokens/{token}", headers=_headers(user))
    assert first.status_code == 204

    db.expire_all()
    row = db.get(models.PushToken, uuid.UUID(created.json()["id"]))
    assert row is not None
    assert row.revoked_at is not None

    second = client.delete(f"/v1/me/push-tokens/{token}", headers=_headers(user))
    assert second.status_code == 204

    again = _register(client, user, token)
    assert again.status_code == 201
    db.expire_all()
    row = db.get(models.PushToken, uuid.UUID(created.json()["id"]))
    assert row is not None
    assert row.revoked_at is None


def test_push_token_endpoints_require_auth_and_validate_payload(client, db):
    user = _customer(db)
    token = "fcm-token-0123456789abcdef"

    assert client.post("/v1/me/push-tokens", json={"token": token, "platform": "android"}).status_code == 401
    assert client.delete(f"/v1/me/push-tokens/{token}").status_code == 401

    short = _register(client, user, "too-short")
    assert short.status_code == 422

    web = _register(client, user, token, platform="web")
    assert web.status_code == 422

    assert client.delete("/v1/me/push-tokens/unknown-token-0123456789", headers=_headers(user)).status_code == 204
