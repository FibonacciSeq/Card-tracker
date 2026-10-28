from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.services.reservations import expire_due_reservations


def _create(client: TestClient, tenant, payload, headers=None):
    return client.post(f"/v1/shops/{tenant.slug}/reservations", json=payload, headers=headers or {})


def test_create_reservation_holds_stock(client, tenant, stock, reservation_payload):
    response = _create(client, tenant, reservation_payload)
    assert response.status_code == 201, response.text

    data = response.json()
    assert data["status"] == "REQUESTED"
    assert data["public_ref"].startswith("R-")
    assert data["total"] == {"amount_minor": 250000, "currency": "RSD"}
    assert data["access_token"]
    assert data["shop"]["slug"] == tenant.slug
    assert data["lines"][0]["quantity"] == 2

    stock_response = client.get(f"/v1/shops/{tenant.slug}/stock").json()
    assert stock_response["items"][0]["available"] == 1


def test_rejects_more_than_available(client, tenant, stock, reservation_payload):
    reservation_payload["items"][0]["quantity"] = 4
    response = _create(client, tenant, reservation_payload)
    assert response.status_code == 409
    assert response.json()["code"] == "stock_changed"
    assert response.json()["lines"][0]["available"] == 3


def test_owner_backorder_flag_does_not_allow_overselling(client, tenant, stock, reservation_payload, db):
    tenant.settings.allow_backorders = True
    db.commit()

    reservation_payload["items"][0]["quantity"] = 4
    response = _create(client, tenant, reservation_payload)
    assert response.status_code == 409
    assert response.json()["code"] == "stock_changed"


def test_all_or_nothing(client, tenant, stock, second_stock, reservation_payload):
    reservation_payload["items"] = [
        {"stock_id": str(stock.id), "quantity": 1},
        {"stock_id": str(second_stock.id), "quantity": 2},
    ]
    response = _create(client, tenant, reservation_payload)
    assert response.status_code == 409
    assert response.json()["code"] == "stock_changed"

    # Nothing was reserved, including the line that was available.
    stock_response = client.get(f"/v1/shops/{tenant.slug}/stock").json()
    by_id = {item["stock_id"]: item for item in stock_response["items"]}
    assert by_id[str(stock.id)]["available"] == 3
    assert by_id[str(second_stock.id)]["available"] == 1


def test_idempotency_key_prevents_double_hold(client, tenant, stock, reservation_payload, db):
    headers = {"Idempotency-Key": "test-key-1"}
    first = _create(client, tenant, reservation_payload, headers=headers)
    second = _create(client, tenant, reservation_payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    # The replay returns the same derived token, not a newly generated one.
    assert first.json()["access_token"] == second.json()["access_token"]
    assert first.json()["access_token"]

    stock_response = client.get(f"/v1/shops/{tenant.slug}/stock").json()
    assert stock_response["items"][0]["available"] == 1

    db.expire_all()
    key = db.get(models.IdempotencyKey, "test-key-1")
    assert key is not None
    assert "access_token" not in key.response


def test_lookup_by_public_ref(client, tenant, stock, reservation_payload):
    created = _create(client, tenant, reservation_payload).json()
    response = client.get(
        f"/v1/shops/{tenant.slug}/reservations/{created['public_ref']}",
        headers={"X-Reservation-Token": created["access_token"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]

    bad = client.get(
        f"/v1/shops/{tenant.slug}/reservations/{created['public_ref']}",
        headers={"X-Reservation-Token": "wrong"},
    )
    assert bad.status_code == 403


def test_cancel_releases_stock(client, tenant, stock, reservation_payload):
    created = _create(client, tenant, reservation_payload).json()
    token = created["access_token"]

    response = client.post(
        f"/v1/reservations/{created['id']}/cancel",
        headers={"X-Reservation-Token": token, "X-Shop-Slug": tenant.slug},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"

    stock_response = client.get(f"/v1/shops/{tenant.slug}/stock").json()
    assert stock_response["items"][0]["available"] == 3


def test_cancel_requires_token(client, tenant, stock, reservation_payload):
    created = _create(client, tenant, reservation_payload).json()
    response = client.post(
        f"/v1/reservations/{created['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug},
    )
    assert response.status_code == 403


def test_expiry_releases_stock(client, tenant, stock, reservation_payload, db):
    created = _create(client, tenant, reservation_payload).json()

    reservation = db.get(models.Reservation, uuid.UUID(created["id"]))
    assert reservation is not None
    reservation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert expire_due_reservations(db) == 1

    db.expire_all()
    reservation = db.get(models.Reservation, uuid.UUID(created["id"]))
    stock_row = db.get(models.Stock, stock.id)
    assert reservation is not None and reservation.status == "EXPIRED"
    assert stock_row is not None and stock_row.reserved == 0
    assert stock_row.available == 3

    note = (
        db.query(models.Notification)
        .filter_by(kind="RESERVATION_EXPIRED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None
    assert note.recipient == "marko@example.com"
    assert note.channel == "email"


def test_movement_ledger_created(client, tenant, stock, reservation_payload, db):
    _create(client, tenant, reservation_payload)
    db.expire_all()
    count = db.scalar(
        select(func.count()).select_from(models.StockMovement).where(models.StockMovement.tenant_id == tenant.id)
    )
    assert count == 1
    movement = db.scalar(select(models.StockMovement))
    assert movement is not None
    assert movement.kind == "RESERVE"
    assert movement.reserved_delta == 2
    assert movement.on_hand_delta == 0
