from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import models
from app.services import notifications
from app.services.reservations import expire_due_reservations


def _notification(
    db,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str = "RESERVATION_CREATED",
    channel: str = "in_app",
    payload: dict | None = None,
    read_at: datetime | None = None,
) -> models.Notification:
    row = models.Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        kind=kind,
        channel=channel,
        payload=payload or {"public_ref": "R-ABC123", "customer_name": "Ana"},
        sent_at=datetime.now(UTC),
        read_at=read_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _cancel_url(reservation_id: str) -> str:
    return f"/v1/reservations/{reservation_id}/cancel"


def test_staff_inbox_lists_notifications_with_unread_counts_and_pagination(client, auth, tenant, owner, db):
    already_read = _notification(
        db,
        tenant_id=tenant.id,
        user_id=owner.id,
        kind="CARD_REQUEST_ACCEPTED",
        read_at=datetime.now(UTC),
    )
    oldest = _notification(db, tenant_id=tenant.id, user_id=owner.id, kind="CARD_REQUEST_CREATED")
    middle = _notification(db, tenant_id=tenant.id, user_id=owner.id, kind="RESERVATION_CREATED")
    newest = _notification(
        db,
        tenant_id=tenant.id,
        user_id=owner.id,
        kind="RESERVATION_CANCELLED",
        payload={"public_ref": "R-2", "customer_name": "Ana", "reason": "Customer changed their mind"},
    )
    _notification(db, tenant_id=tenant.id, user_id=uuid.uuid4(), kind="RESERVATION_CREATED")
    _notification(db, tenant_id=tenant.id, user_id=owner.id, kind="RESERVATION_CREATED", channel="push")

    response = client.get("/v1/staff/notifications?limit=2", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unread_count"] == 3
    assert [item["id"] for item in body["items"]] == [newest.id, middle.id]
    assert body["next_cursor"] == str(middle.id)
    assert body["items"][0]["title"] == "Reservation R-2 cancelled"
    assert "Customer changed their mind" in body["items"][0]["body"]
    assert body["items"][0]["link"] == "/reservations"
    assert body["items"][0]["read_at"] is None
    assert body["items"][1]["title"] == "New reservation R-ABC123"
    assert body["items"][1]["link"] == "/reservations"

    second_page = client.get(
        f"/v1/staff/notifications?limit=2&cursor={body['next_cursor']}",
        headers=auth,
    )
    second = second_page.json()
    assert [item["id"] for item in second["items"]] == [oldest.id, already_read.id]
    assert second["next_cursor"] is None
    assert second["unread_count"] == 3

    assert client.get("/v1/staff/notifications").status_code == 401
    assert client.get("/v1/staff/notifications?cursor=0", headers=auth).status_code == 422
    assert client.get("/v1/staff/notifications?limit=0", headers=auth).status_code == 422
    assert client.get("/v1/staff/notifications?limit=201", headers=auth).status_code == 422


def test_marking_notifications_read_is_scoped_to_the_signed_in_staff(client, auth, tenant, owner, other_tenant, db):
    first = _notification(db, tenant_id=tenant.id, user_id=owner.id)
    second = _notification(db, tenant_id=tenant.id, user_id=owner.id)
    other_tenant_row = _notification(db, tenant_id=other_tenant.id, user_id=owner.id)
    push_row = _notification(db, tenant_id=tenant.id, user_id=owner.id, channel="push")

    read = client.post(f"/v1/staff/notifications/{first.id}/read", headers=auth)
    assert read.status_code == 200, read.text
    assert read.json()["read_at"] is not None
    again = client.post(f"/v1/staff/notifications/{first.id}/read", headers=auth)
    assert again.status_code == 200
    assert again.json()["read_at"] is not None
    assert client.post(f"/v1/staff/notifications/{other_tenant_row.id}/read", headers=auth).status_code == 404
    assert client.post(f"/v1/staff/notifications/{push_row.id}/read", headers=auth).status_code == 404
    assert client.post("/v1/staff/notifications/999999/read", headers=auth).status_code == 404

    unread = client.get("/v1/staff/notifications?limit=10", headers=auth).json()
    assert unread["unread_count"] == 1
    assert {item["id"] for item in unread["items"]} == {first.id, second.id}

    cleared = client.post("/v1/staff/notifications/read-all", headers=auth)
    assert cleared.status_code == 200
    assert cleared.json() == {"updated": 1}
    assert client.post("/v1/staff/notifications/read-all", headers=auth).json() == {"updated": 0}

    after = client.get("/v1/staff/notifications?limit=10", headers=auth).json()
    assert after["unread_count"] == 0
    assert {item["id"] for item in after["items"]} == {first.id, second.id}
    assert all(item["read_at"] is not None for item in after["items"])
    assert client.post("/v1/staff/notifications/read-all").status_code == 401


def test_new_reservations_notify_every_active_staff_member(client, auth, tenant, owner, stock, reservation_payload, db):
    inactive = models.User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="inactive@example.com",
        role="staff",
        is_active=False,
    )
    db.add(inactive)
    db.commit()

    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text

    feed = client.get("/v1/staff/notifications", headers=auth).json()
    created_item = next(item for item in feed["items"] if item["kind"] == "RESERVATION_CREATED")
    assert created_item["title"].startswith("New reservation R-")
    assert "Marko Petrovic" in created_item["body"]
    assert "Confirm it before" in created_item["body"]

    rows = db.query(models.Notification).filter_by(kind="RESERVATION_CREATED").all()
    assert [row.user_id for row in rows] == [owner.id]

    cancelled = client.post(
        _cancel_url(created.json()["id"]),
        headers={"X-Reservation-Token": created.json()["access_token"], "X-Shop-Slug": tenant.slug},
    )
    assert cancelled.status_code == 200, cancelled.text

    feed = client.get("/v1/staff/notifications", headers=auth).json()
    cancelled_item = next(item for item in feed["items"] if item["kind"] == "RESERVATION_CANCELLED")
    assert cancelled_item["title"].startswith("Reservation R-")
    assert "cancelled the hold" in cancelled_item["body"]
    assert cancelled_item["link"] == "/reservations"


def test_expired_reservations_notify_staff(client, tenant, owner, stock, reservation_payload, db):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload).json()
    reservation = db.get(models.Reservation, uuid.UUID(created["id"]))
    assert reservation is not None
    reservation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert expire_due_reservations(db) == 1
    db.expire_all()

    row = db.query(models.Notification).filter_by(kind="RESERVATION_EXPIRED").one()
    assert row.user_id == owner.id
    title, body = notifications.render_staff(row, tenant)
    assert title.startswith("Reservation R-")
    assert "expired and the cards are back in stock" in body


def test_special_order_events_notify_staff(client, auth, tenant, card, owner, db):
    created = client.post(
        f"/v1/shops/{tenant.slug}/card-requests",
        json={
            "customer": {"name": "Ana Ilic", "email": "ana@example.com", "phone": "+38160111222"},
            "card_id": str(card.id),
            "quantity": 2,
            "note": "Clean copy please.",
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()

    feed = client.get("/v1/staff/notifications", headers=auth).json()
    created_item = next(item for item in feed["items"] if item["kind"] == "CARD_REQUEST_CREATED")
    assert created_item["title"] == f"New special order {data['public_ref']}"
    assert "Ana Ilic asked for 2 x Lightning Bolt" in created_item["body"]
    assert created_item["link"] == "/requests"

    quoted = client.post(
        f"/v1/staff/card-requests/{data['id']}/quote",
        headers=auth,
        json={"quote_price_minor": 275000, "vendor_note": "Can have it Friday."},
    )
    assert quoted.status_code == 200, quoted.text

    accepted = client.post(
        f"/v1/card-requests/{data['id']}/accept",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": data["access_token"]},
    )
    assert accepted.status_code == 200, accepted.text

    feed = client.get("/v1/staff/notifications", headers=auth).json()
    accepted_item = next(item for item in feed["items"] if item["kind"] == "CARD_REQUEST_ACCEPTED")
    assert accepted_item["title"] == f"Quote {data['public_ref']} accepted"
    assert "Source the card" in accepted_item["body"]
    assert accepted_item["link"] == "/requests"

    second = client.post(
        f"/v1/shops/{tenant.slug}/card-requests",
        json={
            "customer": {"name": "Ana Ilic", "email": "ana@example.com"},
            "requested_name": "Mox Pearl",
        },
    ).json()
    cancelled = client.post(
        f"/v1/card-requests/{second['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": second["access_token"]},
    )
    assert cancelled.status_code == 200, cancelled.text

    feed = client.get("/v1/staff/notifications", headers=auth).json()
    cancelled_item = next(item for item in feed["items"] if item["kind"] == "CARD_REQUEST_CANCELLED")
    assert cancelled_item["title"] == f"Special order {second['public_ref']} cancelled"
    assert "cancelled the request for Mox Pearl" in cancelled_item["body"]

    rows = db.query(models.Notification).filter_by(kind="CARD_REQUEST_CREATED").all()
    assert len(rows) == 2
    assert all(row.user_id == owner.id for row in rows)


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("RESERVATION_CREATED", {"public_ref": "R-1", "customer_name": "Ana", "line_count": 2, "total_minor": 5000}),
        ("RESERVATION_CANCELLED", {"public_ref": "R-1", "customer_name": "Ana"}),
        ("RESERVATION_CANCELLED", {"public_ref": "R-1", "customer_name": "Ana", "reason": "Duplicate"}),
        ("RESERVATION_EXPIRED", {"public_ref": "R-1", "customer_name": "Ana"}),
        ("CARD_REQUEST_CREATED", {"public_ref": "Q-1", "customer_name": "Ana", "requested_name": "Bolt"}),
        ("CARD_REQUEST_ACCEPTED", {"public_ref": "Q-1", "customer_name": "Ana", "requested_name": "Bolt"}),
        ("CARD_REQUEST_CANCELLED", {"public_ref": "Q-1", "customer_name": "Ana", "requested_name": "Bolt"}),
        ("SOMETHING_ELSE", {"public_ref": "X-1"}),
    ],
)
def test_staff_notification_rendering_covers_every_kind(tenant, kind, payload):
    row = models.Notification(
        tenant_id=tenant.id,
        user_id=uuid.uuid4(),
        kind=kind,
        channel="in_app",
        payload=payload,
    )
    title, body = notifications.render_staff(row, tenant)
    assert title
    assert body


def test_staff_links_point_at_the_matching_queue():
    assert notifications.staff_link("RESERVATION_CREATED") == "/reservations"
    assert notifications.staff_link("CARD_REQUEST_CREATED") == "/requests"
    assert notifications.staff_link("SOMETHING_ELSE") == "/"
