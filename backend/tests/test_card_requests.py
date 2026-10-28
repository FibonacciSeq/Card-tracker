from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import models
from app.services import card_requests as request_service


def _payload(card, **overrides):
    payload = {
        "customer": {"name": "Ana Ilic", "email": "Ana@Example.com", "phone": "+38160111222"},
        "card_id": str(card.id),
        "requested_name": "",
        "quantity": 2,
        "target_price_minor": 300000,
        "note": "Would prefer a clean copy.",
    }
    payload.update(overrides)
    return payload


def _create(client, tenant, card, **overrides):
    response = client.post(f"/v1/shops/{tenant.slug}/card-requests", json=_payload(card, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _quote(client, auth, request_id, **overrides):
    body = {"quote_price_minor": 275000, "vendor_note": "Can have it Friday."}
    body.update(overrides)
    response = client.post(f"/v1/staff/card-requests/{request_id}/quote", headers=auth, json=body)
    return response


def _accept(client, tenant, request_id, token):
    return client.post(
        f"/v1/card-requests/{request_id}/accept",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": token},
    )


def test_guest_creates_a_request_with_a_tracking_token(client, tenant, card):
    data = _create(client, tenant, card)

    assert data["status"] == "REQUESTED"
    assert data["public_ref"].startswith("Q-")
    assert data["requested_name"] == "Lightning Bolt"
    assert data["set_code"] == "LEB"
    assert data["target_price"] == {"amount_minor": 300000, "currency": "RSD"}
    assert data["access_token"]
    assert data["quote_price"] is None


def test_guest_can_read_but_not_without_the_token(client, tenant, card):
    data = _create(client, tenant, card)
    headers = {"X-Shop-Slug": tenant.slug}

    assert client.get(f"/v1/card-requests/{data['id']}", headers=headers).status_code == 403
    wrong = {**headers, "X-Card-Request-Token": "nope"}
    assert client.get(f"/v1/card-requests/{data['id']}", headers=wrong).status_code == 403

    ok = {**headers, "X-Card-Request-Token": data["access_token"]}
    fetched = client.get(f"/v1/card-requests/{data['id']}", headers=ok)
    assert fetched.status_code == 200
    assert fetched.json()["public_ref"] == data["public_ref"]


def test_staff_queue_includes_contact_details(client, auth, tenant, card):
    data = _create(client, tenant, card)

    queue = client.get("/v1/staff/card-requests", headers=auth)
    assert queue.status_code == 200
    row = next(item for item in queue.json() if item["id"] == data["id"])
    assert row["customer_email"] == "ana@example.com"
    assert row["customer_phone"] == "+38160111222"
    assert row["customer_note"] == "Would prefer a clean copy."


def test_quote_notifies_the_customer_and_is_audited(client, auth, tenant, card, db):
    data = _create(client, tenant, card)
    quote = _quote(
        client,
        auth,
        data["id"],
        quote_expires_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    assert quote.status_code == 200, quote.text
    body = quote.json()
    assert body["status"] == "QUOTED"
    assert body["quote_price"] == {"amount_minor": 275000, "currency": "RSD"}
    assert body["vendor_note"] == "Can have it Friday."

    note = (
        db.query(models.Notification)
        .filter_by(kind="CARD_REQUEST_QUOTED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None
    assert note.recipient == "ana@example.com"
    assert note.channel == "email"

    audit = client.get("/v1/staff/audit?action=card_request", headers=auth).json()
    assert any(event["action"] == "card_request.quote" for event in audit)


def test_customer_accepts_the_quote(client, auth, tenant, card):
    data = _create(client, tenant, card)
    _quote(client, auth, data["id"])

    accepted = _accept(client, tenant, data["id"], data["access_token"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ACCEPTED"

    staff_note = client.get("/v1/staff/card-requests?status=ACCEPTED", headers=auth).json()
    assert [row["id"] for row in staff_note] == [data["id"]]


def test_declined_requests_cannot_be_accepted(client, auth, tenant, card):
    data = _create(client, tenant, card)
    declined = client.post(
        f"/v1/staff/card-requests/{data['id']}/decline",
        headers=auth,
        json={"vendor_note": "Out of print."},
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "DECLINED"

    accepted = _accept(client, tenant, data["id"], data["access_token"])
    assert accepted.status_code == 409


def test_expired_quote_is_rejected(client, auth, tenant, card, db):
    data = _create(client, tenant, card)
    row = db.get(models.CardRequest, uuid.UUID(data["id"]))
    assert row is not None
    row.status = "QUOTED"
    row.quote_price_minor = 275000
    row.quote_currency = "RSD"
    row.quote_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    accepted = _accept(client, tenant, data["id"], data["access_token"])
    assert accepted.status_code == 409
    assert "expired" in accepted.text.lower()

    fetched = client.get(
        f"/v1/card-requests/{data['id']}",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": data["access_token"]},
    )
    assert fetched.json()["status"] == "EXPIRED"

    db.expire_all()
    note = (
        db.query(models.Notification)
        .filter_by(kind="CARD_REQUEST_EXPIRED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None and note.recipient == "ana@example.com"


def test_expiry_worker_expires_stale_quotes(client, auth, tenant, card, db):
    data = _create(client, tenant, card)
    row = db.get(models.CardRequest, uuid.UUID(data["id"]))
    assert row is not None
    row.status = "QUOTED"
    row.quote_price_minor = 275000
    row.quote_currency = "RSD"
    row.quote_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()

    assert request_service.expire_due_quotes(db) == 1
    db.expire_all()
    row = db.get(models.CardRequest, uuid.UUID(data["id"]))
    assert row is not None and row.status == "EXPIRED"

    note = (
        db.query(models.Notification)
        .filter_by(kind="CARD_REQUEST_EXPIRED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None and note.recipient == "ana@example.com"


def test_quote_rejects_an_expiry_in_the_past(client, auth, tenant, card):
    data = _create(client, tenant, card)
    response = _quote(
        client,
        auth,
        data["id"],
        quote_expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    assert response.status_code == 422
    assert "future" in response.json()["detail"]


def test_staff_can_decline_an_accepted_request(client, auth, tenant, card):
    data = _create(client, tenant, card)
    _quote(client, auth, data["id"])
    assert _accept(client, tenant, data["id"], data["access_token"]).status_code == 200

    declined = client.post(
        f"/v1/staff/card-requests/{data['id']}/decline",
        headers=auth,
        json={"vendor_note": "The supplier cancelled."},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "DECLINED"


def test_expiry_worker_expires_abandoned_accepted_requests(client, auth, tenant, card, db):
    data = _create(client, tenant, card)
    _quote(client, auth, data["id"])
    assert _accept(client, tenant, data["id"], data["access_token"]).status_code == 200

    row = db.get(models.CardRequest, uuid.UUID(data["id"]))
    assert row is not None
    row.updated_at = datetime.now(UTC) - timedelta(days=request_service.ACCEPTED_EXPIRY_DAYS + 1)
    db.commit()

    assert request_service.expire_due_quotes(db) == 1
    db.expire_all()
    row = db.get(models.CardRequest, uuid.UUID(data["id"]))
    assert row is not None and row.status == "EXPIRED"


def test_conversion_creates_a_confirmed_reservation(client, auth, tenant, card, stock, db):
    data = _create(client, tenant, card, quantity=2)
    _quote(client, auth, data["id"])
    _accept(client, tenant, data["id"], data["access_token"])

    converted = client.post(f"/v1/staff/card-requests/{data['id']}/convert", headers=auth, json={})
    assert converted.status_code == 200, converted.text
    body = converted.json()
    assert body["status"] == "CONVERTED"
    assert body["reservation_ref"].startswith("R-")
    assert body["reservation_id"]

    db.expire_all()
    reservation = db.get(models.Reservation, uuid.UUID(body["reservation_id"]))
    assert reservation is not None
    assert reservation.status == "CONFIRMED"
    assert reservation.source == "staff"
    assert len(reservation.lines) == 1
    assert reservation.lines[0].quantity == 2

    updated_stock = db.get(models.Stock, stock.id)
    assert updated_stock is not None
    assert updated_stock.reserved == 2
    assert updated_stock.available == 1

    note = (
        db.query(models.Notification)
        .filter_by(kind="CARD_REQUEST_CONVERTED")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None and note.recipient == "ana@example.com"

    audit = client.get("/v1/staff/audit?action=card_request", headers=auth).json()
    assert any(event["action"] == "card_request.convert" for event in audit)


def test_conversion_needs_the_matching_variant_in_stock(client, auth, tenant, card):
    data = _create(client, tenant, card, finish="foil")
    _quote(client, auth, data["id"])
    _accept(client, tenant, data["id"], data["access_token"])

    converted = client.post(f"/v1/staff/card-requests/{data['id']}/convert", headers=auth, json={})
    assert converted.status_code == 409
    assert "Add this exact card" in converted.json()["detail"]


def test_conversion_refuses_to_overdraw_stock(client, auth, tenant, card, stock):
    data = _create(client, tenant, card, quantity=10)
    _quote(client, auth, data["id"])
    _accept(client, tenant, data["id"], data["access_token"])

    converted = client.post(f"/v1/staff/card-requests/{data['id']}/convert", headers=auth, json={})
    assert converted.status_code == 409
    assert "Only 3 available" in converted.json()["detail"]


def test_customer_can_cancel_a_request(client, tenant, card):
    data = _create(client, tenant, card)
    cancelled = client.post(
        f"/v1/card-requests/{data['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": data["access_token"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    again = client.post(
        f"/v1/card-requests/{data['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": data["access_token"]},
    )
    assert again.status_code == 409


def test_free_text_requests_do_not_need_a_catalog_card(client, tenant):
    response = client.post(
        f"/v1/shops/{tenant.slug}/card-requests",
        json={
            "customer": {"name": "Ana", "email": "ana@example.com"},
            "requested_name": "Mox Pearl",
            "set_code": "LEA",
            "collector_number": "259",
            "quantity": 1,
        },
    )
    assert response.status_code == 201
    assert response.json()["requested_name"] == "Mox Pearl"
    assert response.json()["card_id"] is None
