from __future__ import annotations

from app.config import settings
from app.services.ratelimit import SlidingWindowLimiter


def test_sliding_window_allows_then_blocks_then_forgets():
    limiter = SlidingWindowLimiter()

    assert limiter.hit("k", limit=2, window_seconds=10, now=100.0) is None
    assert limiter.hit("k", limit=2, window_seconds=10, now=101.0) is None
    retry = limiter.hit("k", limit=2, window_seconds=10, now=102.0)
    assert retry == 8.0

    # The first two attempts have aged out of the ten-second window.
    assert limiter.hit("k", limit=2, window_seconds=10, now=111.0) is None


def test_limiter_keys_are_independent():
    limiter = SlidingWindowLimiter()
    assert limiter.hit("a", limit=1, window_seconds=10, now=0.0) is None
    assert limiter.hit("a", limit=1, window_seconds=10, now=0.0) is not None
    assert limiter.hit("b", limit=1, window_seconds=10, now=0.0) is None


def test_login_is_rate_limited(client, tenant, monkeypatch):
    monkeypatch.setattr(settings, "login_rate_limit", 2)

    payload = {"tenant_slug": tenant.slug, "email": "nobody@example.com", "password": "wrong-password"}
    assert client.post("/v1/staff/auth/login", json=payload).status_code == 401
    assert client.post("/v1/staff/auth/login", json=payload).status_code == 401

    blocked = client.post("/v1/staff/auth/login", json=payload)
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json()["detail"]
    assert int(blocked.headers["retry-after"]) >= 1


def test_successful_logins_consume_the_budget(client, owner, tenant, monkeypatch):
    monkeypatch.setattr(settings, "login_rate_limit", 1)

    payload = {"tenant_slug": tenant.slug, "email": owner.email, "password": "secret-password"}
    assert client.post("/v1/staff/auth/login", json=payload).status_code == 200
    assert client.post("/v1/staff/auth/login", json=payload).status_code == 429


def test_reservation_creation_is_rate_limited(client, tenant, stock, reservation_payload, monkeypatch):
    monkeypatch.setattr(settings, "reservation_rate_limit", 1)

    first = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert first.status_code == 201

    blocked = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
