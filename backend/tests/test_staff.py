from __future__ import annotations

import uuid

from app import models


def _create(client, tenant, payload):
    return client.post(f"/v1/shops/{tenant.slug}/reservations", json=payload)


def test_staff_login(client, tenant, owner):
    response = client.post(
        "/v1/staff/auth/login",
        json={
            "tenant_slug": tenant.slug,
            "email": owner.email,
            "password": "secret-password",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_staff_login_rejects_bad_password(client, tenant, owner):
    response = client.post(
        "/v1/staff/auth/login",
        json={
            "tenant_slug": tenant.slug,
            "email": owner.email,
            "password": "wrong",
        },
    )
    assert response.status_code == 401


def test_staff_sees_reserved_and_available(client, tenant, stock, reservation_payload, auth):
    _create(client, tenant, reservation_payload)
    response = client.get("/v1/staff/stock", headers=auth)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["on_hand"] == 3
    assert item["reserved"] == 2
    assert item["available"] == 1


def test_staff_cannot_reduce_below_reserved(client, tenant, stock, reservation_payload, auth):
    _create(client, tenant, reservation_payload)

    response = client.patch(
        f"/v1/staff/stock/{stock.id}",
        json={"quantity": 1},
        headers=auth,
    )
    assert response.status_code == 409

    response = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": -3, "reason": "test"},
        headers=auth,
    )
    assert response.status_code == 409


def test_complete_reservation_sells_stock(client, tenant, stock, reservation_payload, auth, db):
    created = _create(client, tenant, reservation_payload).json()

    response = client.post(
        f"/v1/staff/reservations/{created['id']}/complete",
        json={},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"

    db.expire_all()
    stock_row = db.get(models.Stock, stock.id)
    assert stock_row is not None
    assert stock_row.quantity == 1
    assert stock_row.reserved == 0

    movements = db.query(models.StockMovement).filter_by(stock_id=stock.id).all()
    assert any(m.kind == "SELL" for m in movements)

    note = (
        db.query(models.Notification)
        .filter_by(kind="RESERVATION_COMPLETED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None
    assert note.recipient == "marko@example.com"


def test_partial_completion_releases_the_rest(client, tenant, stock, reservation_payload, auth, db):
    created = _create(client, tenant, reservation_payload).json()
    line_id = created["lines"][0]["line_id"]

    response = client.post(
        f"/v1/staff/reservations/{created['id']}/complete",
        json={"lines": [{"line_id": line_id, "complete_quantity": 1, "cancel_quantity": 1}]},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"

    db.expire_all()
    stock_row = db.get(models.Stock, stock.id)
    assert stock_row is not None
    assert stock_row.quantity == 2
    assert stock_row.reserved == 0


def test_cancel_after_partial_completion_keeps_completed_status(client, tenant, stock, reservation_payload, auth, db):
    created = _create(client, tenant, reservation_payload).json()
    line_id = created["lines"][0]["line_id"]

    response = client.post(
        f"/v1/staff/reservations/{created['id']}/complete",
        json={"lines": [{"line_id": line_id, "complete_quantity": 1, "cancel_quantity": 0}]},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/v1/staff/reservations/{created['id']}/status",
        json={"status": "CANCELLED", "reason": "customer changed their mind"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"

    db.expire_all()
    stock_row = db.get(models.Stock, stock.id)
    assert stock_row is not None
    assert stock_row.quantity == 2
    assert stock_row.reserved == 0


def test_record_in_store_sale(client, tenant, stock, auth, db):
    response = client.post(
        f"/v1/staff/stock/{stock.id}/sell",
        json={"quantity": 2},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["on_hand"] == 1

    db.expire_all()
    stock_row = db.get(models.Stock, stock.id)
    assert stock_row is not None and stock_row.quantity == 1


def test_dashboard(client, tenant, stock, reservation_payload, auth):
    _create(client, tenant, reservation_payload)
    response = client.get("/v1/staff/dashboard", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert data["pending_reservations"] == 1
    assert data["active_reservations"] == 1


def test_confirm_then_ready(client, tenant, stock, reservation_payload, auth):
    created = _create(client, tenant, reservation_payload).json()

    response = client.post(
        f"/v1/staff/reservations/{created['id']}/status",
        json={"status": "CONFIRMED"},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"

    response = client.post(
        f"/v1/staff/reservations/{created['id']}/status",
        json={"status": "READY"},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "READY"


def test_staff_cannot_read_other_reservation(client, tenant, other_tenant, stock, reservation_payload, owner, db):
    created = _create(client, tenant, reservation_payload).json()

    other_owner = models.User(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        email="other@example.com",
        role="owner",
    )
    db.add(other_owner)
    db.commit()

    from app.security import create_access_token

    headers = {"Authorization": f"Bearer {create_access_token(other_owner.id, other_tenant.id, 'owner')}"}
    response = client.get(f"/v1/staff/reservations/{created['id']}", headers=headers)
    assert response.status_code == 404


def test_staff_reservation_view_includes_contact_details(client, tenant, stock, reservation_payload, auth):
    """Staff need contact details and the note; the public view must not add them."""
    created = _create(client, tenant, reservation_payload)
    assert created.status_code == 201, created.text
    public = created.json()
    assert "customer_email" not in public
    assert "customer_phone" not in public
    assert "note" not in public

    listing = client.get("/v1/staff/reservations", headers=auth)
    assert listing.status_code == 200
    assert listing.json()[0]["customer_name"] == reservation_payload["customer"]["name"]

    detail = client.get(f"/v1/staff/reservations/{public['id']}", headers=auth)
    assert detail.status_code == 200
    data = detail.json()
    assert data["customer_name"] == reservation_payload["customer"]["name"]
    assert data["customer_email"] == reservation_payload["customer"]["email"]
    assert data["customer_phone"] == reservation_payload["customer"]["phone"]
    assert data["note"] == reservation_payload["note"]


def test_settings_include_alert_email_but_public_profile_does_not(client, tenant, auth, db):
    tenant.settings.notification_email = "orders@example.com"
    db.add(tenant.settings)
    db.commit()

    staff = client.get("/v1/staff/settings", headers=auth)
    assert staff.status_code == 200
    assert staff.json()["notification_email"] == "orders@example.com"

    public = client.get(f"/v1/shops/{tenant.slug}")
    assert public.status_code == 200
    assert "notification_email" not in public.json()


def test_staff_alert_falls_back_to_the_public_contact_email(client, tenant, stock, reservation_payload, db):
    tenant.settings.notification_email = None
    tenant.settings.contact = {"email": "hello@shop.example"}
    db.add(tenant.settings)
    db.commit()

    created = _create(client, tenant, reservation_payload)
    assert created.status_code == 201, created.text

    db.expire_all()
    note = (
        db.query(models.Notification)
        .filter_by(kind="RESERVATION_CREATED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None
    assert note.recipient == "hello@shop.example"


def test_new_stock_rejects_a_mismatched_currency(client, tenant, card, auth):
    response = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={
            "card_id": str(card.id),
            "finish": "foil",
            "condition": "NM",
            "language": "en",
            "quantity": 1,
            "price_minor": 1000,
            "currency": "EUR",
        },
    )
    assert response.status_code == 422
    assert "shop currency" in response.json()["detail"]


def test_new_stock_rejects_an_invalid_language(client, tenant, card, auth):
    response = client.post(
        "/v1/staff/stock",
        headers=auth,
        json={
            "card_id": str(card.id),
            "finish": "etched",
            "condition": "NM",
            "language": "english",
            "quantity": 1,
            "price_minor": 1000,
        },
    )
    assert response.status_code == 422
    assert "language" in response.json()["detail"]
