"""Coverage for public, account, and staff API edge paths."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import models, schemas
from app.api import account as account_api
from app.api import public as public_api
from app.api import staff as staff_api
from app.config import settings
from app.security import create_access_token, create_customer_access_token, restock_unsubscribe_token


def _customer(db, email="customer@example.com"):
    row = models.User(
        id=uuid.uuid4(),
        tenant_id=None,
        email=email,
        role="customer",
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _headers(customer):
    return {"Authorization": f"Bearer {create_customer_access_token(customer.id)}"}


def _reservation(db, tenant, customer=None, ref="R-EDGE", status="REQUESTED"):
    row = models.Reservation(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        customer_id=customer.id if customer else None,
        public_ref=ref,
        customer_name=customer.email if customer else "Guest",
        email=customer.email if customer else "guest@example.com",
        phone="",
        note="",
        status=status,
        total_minor=0,
        currency="RSD",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _card_request(db, tenant, customer, ref="Q-EDGE", status="QUOTED"):
    row = models.CardRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        customer_id=customer.id,
        public_ref=ref,
        customer_name="Customer",
        email=customer.email,
        phone="",
        requested_name="Lightning Bolt",
        finish="nonfoil",
        condition="NM",
        language="en",
        quantity=1,
        currency="RSD",
        status=status,
        access_token_hash="x",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ------------------------------------------------------------------ account


def test_account_owned_reservation_missing_and_tenant_missing(client, db, tenant):
    customer = _customer(db)
    response = client.get(f"/v1/me/reservations/{uuid.uuid4()}", headers=_headers(customer))
    assert response.status_code == 404

    reservation = _reservation(db, tenant, customer)
    found, found_tenant = account_api._owned_reservation(db, customer, reservation.id)
    assert found.id == reservation.id
    assert found_tenant.id == tenant.id

    original_get = db.get

    def get(model, ident, *args, **kwargs):
        if model is models.Tenant:
            return None
        return original_get(model, ident, *args, **kwargs)

    db.get = get
    try:
        with pytest.raises(HTTPException) as exc:
            account_api._owned_reservation(db, customer, reservation.id, with_lines=True)
        assert exc.value.status_code == 404
    finally:
        db.get = original_get


def test_account_owned_card_request_missing_tenant_missing_and_success(client, db, tenant, monkeypatch):
    customer = _customer(db)
    response = client.get(f"/v1/me/card-requests/{uuid.uuid4()}", headers=_headers(customer))
    assert response.status_code == 404

    row = _card_request(db, tenant, customer)
    original_get = db.get

    def get(model, ident, *args, **kwargs):
        if model is models.Tenant:
            return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    with pytest.raises(HTTPException) as exc:
        account_api._owned_card_request(db, customer, row.id)
    assert exc.value.status_code == 404

    monkeypatch.setattr(db, "get", original_get)
    response = client.get(f"/v1/me/card-requests/{row.id}", headers=_headers(customer))
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(row.id)
    assert response.json()["shop"]["slug"] == tenant.slug


def test_account_delete_missing_alert_is_idempotent(client, db):
    customer = _customer(db)
    response = client.delete(f"/v1/me/restock-alerts/{uuid.uuid4()}", headers=_headers(customer))
    assert response.status_code == 204


# ------------------------------------------------------------------- public


def test_public_shop_query_and_stock_filters(client, tenant, card, stock):
    listed = client.get("/v1/shops", params={"query": "bolt"})
    assert listed.status_code == 200
    assert listed.json()[0]["slug"] == tenant.slug

    response = client.get(
        f"/v1/shops/{tenant.slug}/stock",
        params={
            "query": "bolt",
            "set_code": "leb",
            "rarity": "common",
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
            "min_price_minor": 1,
            "max_price_minor": 999999,
            "available_only": "true",
            "sort": "price_asc",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["stock_id"] == str(stock.id)


def test_public_cursor_errors_and_variants(client, tenant, stock):
    bad_type = base64.urlsafe_b64encode(b"[]").decode()
    invalid = client.get(f"/v1/shops/{tenant.slug}/stock", params={"cursor": bad_type})
    assert invalid.status_code == 400

    garbage = client.get(f"/v1/shops/{tenant.slug}/stock", params={"cursor": "!!!"})
    assert garbage.status_code == 400

    missing_price = public_api._encode_cursor(i=str(stock.id))
    bad_fields = client.get(
        f"/v1/shops/{tenant.slug}/stock",
        params={"sort": "price_asc", "cursor": missing_price},
    )
    assert bad_fields.status_code == 400

    price_cursor = public_api._encode_cursor(p=stock.price_minor, i=str(stock.id))
    price_page = client.get(
        f"/v1/shops/{tenant.slug}/stock",
        params={"sort": "price_asc", "cursor": price_cursor},
    )
    assert price_page.status_code == 200

    newest_cursor = public_api._encode_cursor(t=stock.created_at.isoformat(), i=str(stock.id))
    newest_page = client.get(
        f"/v1/shops/{tenant.slug}/stock",
        params={"sort": "newest", "cursor": newest_cursor},
    )
    assert newest_page.status_code == 200


def test_public_stock_item_health_and_missing_lookups(client, tenant, stock):
    found = client.get(f"/v1/shops/{tenant.slug}/stock/{stock.id}")
    assert found.status_code == 200
    assert found.json()["stock_id"] == str(stock.id)

    missing = client.get(f"/v1/shops/{tenant.slug}/stock/{uuid.uuid4()}")
    assert missing.status_code == 404

    assert client.get("/v1/health").json()["status"] == "ok"

    by_id = client.get(
        f"/v1/reservations/{uuid.uuid4()}",
        headers={"X-Shop-Slug": tenant.slug},
    )
    assert by_id.status_code == 404

    by_ref = client.get(f"/v1/shops/{tenant.slug}/reservations/NOPE")
    assert by_ref.status_code == 404


def test_restock_subscription_attaches_an_existing_guest_alert(client, db, tenant, card):
    guest = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json={
            "email": "attach@example.com",
            "card_id": str(card.id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
        },
    )
    assert guest.status_code == 201, guest.text

    customer = _customer(db, "attach@example.com")
    response = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        headers=_headers(customer),
        json={
            "email": "attach@example.com",
            "card_id": str(card.id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["already_subscribed"] is True
    db.expire_all()
    assert db.get(models.RestockAlert, uuid.UUID(response.json()["id"])).customer_id == customer.id


def test_restock_unsubscribe_validation_paths(client, tenant, card):
    missing_payload = client.post(f"/v1/shops/{tenant.slug}/restock-alerts/{uuid.uuid4()}/unsubscribe")
    assert missing_payload.status_code == 422

    bad_token = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts/{uuid.uuid4()}/unsubscribe",
        params={"token": "bad"},
    )
    assert bad_token.status_code == 400


def test_restock_unsubscribe_pages_for_missing_rows(client, tenant):
    alert_id = uuid.uuid4()
    token = restock_unsubscribe_token(tenant.id, alert_id)
    page = client.get(
        f"/v1/shops/{tenant.slug}/restock-alerts/{alert_id}/unsubscribe",
        params={"token": token},
    )
    assert page.status_code == 200
    assert "Already unsubscribed" in page.text

    one_click = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts/{alert_id}/unsubscribe/one-click",
        params={"token": "bad"},
    )
    assert one_click.status_code == 400
    assert "Invalid link" in one_click.text


class _SubscribeDB:
    def __init__(self, tenant, card, existing):
        self.info = {}
        self.tenant = tenant
        self.card = card
        self.existing = existing
        self.scalar_calls = 0
        self.commits = 0

    def scalar(self, _stmt):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.tenant
        if self.scalar_calls == 2:
            return None
        return self.existing

    def get(self, model, _ident):
        assert model is models.Card
        return self.card

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def add(self, _row):
        return None

    def commit(self):
        self.commits += 1
        if self.commits == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate"))

    def rollback(self):
        return None

    def refresh(self, _row):
        return None


def _subscribe_direct(db, tenant, card):
    payload = schemas.RestockAlertCreateIn.model_validate(
        {
            "email": "direct@example.com",
            "card_id": str(card.id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
        }
    )
    return public_api.subscribe_restock_alert(tenant.slug, payload, cast(Any, None), None, db)


def test_restock_integrity_error_finds_the_winner(monkeypatch, tenant, card):
    alert = models.RestockAlert(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="direct@example.com",
        card_id=card.id,
        finish="nonfoil",
        condition="NM",
        language="en",
        created_at=datetime.now(UTC),
    )
    db = _SubscribeDB(tenant, card, alert)
    monkeypatch.setattr(public_api.ratelimit, "enforce", lambda *a, **k: None)
    response = _subscribe_direct(db, tenant, card)
    assert response.already_subscribed is True


def test_restock_integrity_error_reraises_without_a_winner(monkeypatch, tenant, card):
    db = _SubscribeDB(tenant, card, None)
    monkeypatch.setattr(public_api.ratelimit, "enforce", lambda *a, **k: None)
    with pytest.raises(IntegrityError):
        _subscribe_direct(db, tenant, card)


# -------------------------------------------------------------------- staff


def test_staff_helpers_and_missing_tenant(db, owner, tenant, monkeypatch):
    assert staff_api._day_start("Not/AZone").tzinfo is not None
    with pytest.raises(HTTPException) as exc:
        staff_api._staff_tenant(cast(Any, SimpleNamespace(tenant_id=None)))
    assert exc.value.status_code == 401

    original_get = db.get

    def get(model, ident, *args, **kwargs):
        if model is models.Tenant:
            return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    with pytest.raises(HTTPException) as exc:
        staff_api._tenant(db, owner)
    assert exc.value.status_code == 404

    monkeypatch.setattr(db, "get", original_get)
    with pytest.raises(HTTPException) as exc:
        staff_api._get_shop_user(db, uuid.uuid4(), owner.id)
    assert exc.value.status_code == 404

    monkeypatch.undo()
    assert staff_api._active_owner_count(db, tenant.id) == 1


def test_staff_login_unknown_shop(client):
    response = client.post(
        "/v1/staff/auth/login",
        json={"tenant_slug": "missing", "email": "x@example.com", "password": "secret-password"},
    )
    assert response.status_code == 401


def test_dependency_rejects_customer_token_with_tenant_and_missing_user(client, owner, tenant, other_tenant):
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(tenant.id),
            "role": "customer",
            "scope": "customer",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": settings.jwt_issuer,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

    ghost = create_customer_access_token(uuid.uuid4())
    response = client.get("/v1/me", headers={"Authorization": f"Bearer {ghost}"})
    assert response.status_code == 401

    response = client.get("/v1/staff/me")
    assert response.status_code == 401

    cross = create_access_token(owner.id, other_tenant.id, owner.role)
    response = client.get("/v1/staff/me", headers={"Authorization": f"Bearer {cross}"})
    assert response.status_code == 401


def test_staff_user_update_display_name_reactivation_and_audit_filters(client, db, auth, tenant, owner):
    created = client.post(
        "/v1/staff/users",
        headers=auth,
        json={"email": "worker@example.com", "password": "secret-password", "role": "staff"},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    client.patch(f"/v1/staff/users/{user_id}", headers=auth, json={"is_active": False})
    updated = client.patch(
        f"/v1/staff/users/{user_id}",
        headers=auth,
        json={"display_name": "Worker", "is_active": True, "role": "owner"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Worker"
    assert updated.json()["role"] == "owner"

    filtered = client.get(
        "/v1/staff/audit",
        headers=auth,
        params={"action": "staff.", "entity_type": "user"},
    )
    assert filtered.status_code == 200
    assert filtered.json()


def test_staff_card_search_and_stock_filters(client, auth, tenant, card, stock):
    cards = client.get("/v1/staff/cards", headers=auth, params={"query": "bolt"})
    assert cards.status_code == 200
    assert cards.json()[0]["id"] == str(card.id)

    rows = client.get("/v1/staff/stock", headers=auth, params={"query": "bolt", "only_online": "true"})
    assert rows.status_code == 200
    assert rows.json()["items"][0]["stock_id"] == str(stock.id)


def test_staff_import_rejects_oversized_and_non_utf8_files(client, auth, tenant):
    oversized = client.post(
        "/v1/staff/stock/import",
        headers=auth,
        files={"file": ("stock.csv", b"x" * (staff_api.MAX_IMPORT_BYTES + 1), "text/csv")},
        data={"dry_run": "true"},
    )
    assert oversized.status_code == 413

    bad = client.post(
        "/v1/staff/stock/import",
        headers=auth,
        files={"file": ("stock.csv", b"\xff\xfe\xfa", "text/csv")},
        data={"dry_run": "true"},
    )
    assert bad.status_code == 400


def test_staff_create_stock_validation_and_success(client, db, auth, tenant, card):
    missing_card = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={"card_id": str(uuid.uuid4()), "quantity": 1},
    )
    assert missing_card.status_code == 404

    bad_language = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={"card_id": str(card.id), "language": "e"},
    )
    assert bad_language.status_code == 422

    bad_currency = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={"card_id": str(card.id), "currency": "EUR"},
    )
    assert bad_currency.status_code == 422

    created = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={
            "card_id": str(card.id),
            "finish": "etched",
            "condition": "LP",
            "language": "EN",
            "quantity": 2,
            "price_minor": 1000,
            "currency": "rsd",
        },
    )
    assert created.status_code == 201, created.text
    stock_id = created.json()["stock_id"]

    duplicate = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={"card_id": str(card.id), "finish": "etched", "condition": "LP", "language": "en"},
    )
    assert duplicate.status_code == 409
    db.expire_all()
    assert db.get(models.Stock, uuid.UUID(stock_id)).quantity == 2


def test_staff_update_stock_paths(client, auth, stock):
    changed = client.patch(
        f"/v1/staff/stock/{stock.id}",
        headers=auth,
        json={"quantity": 5, "price_minor": 2000, "is_online": False},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["on_hand"] == 5

    online = client.patch(f"/v1/staff/stock/{stock.id}", headers=auth, json={"is_online": True})
    assert online.status_code == 200
    assert online.json()["is_online"] is True

    untouched = client.patch(f"/v1/staff/stock/{stock.id}", headers=auth, json={})
    assert untouched.status_code == 200

    negative = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        headers=auth,
        json={"delta": -99},
    )
    assert negative.status_code == 400


def test_staff_sell_conflict_and_missing_stock(client, db, auth, stock):
    stock.reserved = 3
    db.commit()
    response = client.post(
        f"/v1/staff/stock/{stock.id}/sell",
        headers=auth,
        json={"quantity": 1},
    )
    assert response.status_code == 409

    missing = client.patch(f"/v1/staff/stock/{uuid.uuid4()}", headers=auth, json={"quantity": 1})
    assert missing.status_code == 404


def test_staff_reservation_filters_and_status_errors(client, auth, tenant, stock, reservation_payload):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201
    reservation_id = created.json()["id"]

    filtered = client.get(
        "/v1/staff/reservations",
        headers=auth,
        params={"status": "requested", "query": "marko"},
    )
    assert filtered.status_code == 200
    assert filtered.json()[0]["id"] == reservation_id

    invalid = client.post(
        f"/v1/staff/reservations/{reservation_id}/status",
        headers=auth,
        json={"status": "READY"},
    )
    assert invalid.status_code == 409

    missing = client.post(
        f"/v1/staff/reservations/{uuid.uuid4()}/status",
        headers=auth,
        json={"status": "CONFIRMED"},
    )
    assert missing.status_code == 404

    missing_complete = client.post(
        f"/v1/staff/reservations/{uuid.uuid4()}/complete",
        headers=auth,
        json={},
    )
    assert missing_complete.status_code == 404


def test_staff_card_request_missing_and_settings(client, db, auth, tenant):
    missing = client.get(f"/v1/staff/card-requests/{uuid.uuid4()}", headers=auth)
    assert missing.status_code == 404

    assert client.get("/v1/staff/settings", headers=auth).status_code == 200
    empty = client.patch("/v1/staff/settings", headers=auth, json={})
    assert empty.status_code == 200

    db.expire_all()
    tenant.settings = None
    db.commit()
    created = client.patch("/v1/staff/settings", headers=auth, json={"brand_name": "Fresh"})
    assert created.status_code == 200
    assert created.json()["brand_name"] == "Fresh"


def test_public_price_desc_sort_and_valid_token_unsubscribe(client, db, tenant, card, stock):
    page = client.get(f"/v1/shops/{tenant.slug}/stock", params={"sort": "price_desc"})
    assert page.status_code == 200

    alert = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json={
            "email": "token@example.com",
            "card_id": str(card.id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
        },
    )
    assert alert.status_code == 201, alert.text
    body = alert.json()
    token = restock_unsubscribe_token(tenant.id, uuid.UUID(body["id"]))
    removed = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts/{body['id']}/unsubscribe",
        params={"token": token},
    )
    assert removed.status_code == 204
    db.expire_all()
    assert db.get(models.RestockAlert, uuid.UUID(body["id"])) is None


def test_staff_cards_without_query_and_zero_quantity_stock(client, auth, card):
    cards = client.get("/v1/staff/cards", headers=auth)
    assert cards.status_code == 200
    assert cards.json()[0]["id"] == str(card.id)

    created = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={"card_id": str(card.id), "finish": "etched", "condition": "MP", "quantity": 0},
    )
    assert created.status_code == 201, created.text


def test_staff_quote_missing_card_request(client, auth):
    response = client.post(
        f"/v1/staff/card-requests/{uuid.uuid4()}/quote",
        headers=auth,
        json={"quote_price_minor": 100},
    )
    assert response.status_code == 404
