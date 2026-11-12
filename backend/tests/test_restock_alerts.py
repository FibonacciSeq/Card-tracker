from __future__ import annotations

from datetime import UTC, datetime

from app import models
from app.security import create_customer_access_token


def _customer(db, email: str = "reader@example.com") -> models.User:
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


def _customer_headers(user: models.User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_customer_access_token(user.id)}"}


def _subscribe(client, tenant, card, **overrides):
    payload = {
        "email": "Reader@Example.com",
        "name": "Reader",
        "card_id": str(card.id),
        "finish": "nonfoil",
        "condition": "NM",
        "language": "en",
    }
    payload.update(overrides)
    return client.post(f"/v1/shops/{tenant.slug}/restock-alerts", json=payload)


def _subscribe_signed_in(client, tenant, card, customer, **overrides):
    payload = {
        "email": customer.email,
        "name": "Reader",
        "card_id": str(card.id),
        "finish": "nonfoil",
        "condition": "NM",
        "language": "en",
    }
    payload.update(overrides)
    return client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json=payload,
        headers=_customer_headers(customer),
    )


def _restock_notes(db) -> list[models.Notification]:
    return list(db.query(models.Notification).filter_by(kind="RESTOCK_AVAILABLE").all())


def _sold_out(db, stock):
    stock.quantity = 0
    db.commit()
    db.refresh(stock)


def test_subscribe_is_idempotent_and_shows_on_the_stock_list(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)

    first = _subscribe(client, tenant, card)
    assert first.status_code == 201, first.text
    assert first.json()["already_subscribed"] is False
    assert first.json()["email"] == "reader@example.com"
    assert first.json()["manage_token"]

    second = _subscribe(client, tenant, card)
    assert second.status_code == 201
    assert second.json()["already_subscribed"] is True
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["manage_token"] == first.json()["manage_token"]

    rows = client.get("/v1/staff/stock", headers=auth).json()["items"]
    row = next(item for item in rows if item["stock_id"] == str(stock.id))
    assert row["restock_waiting"] == 1


def test_restock_notifies_waiting_customers_and_clears_the_count(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)
    customer = _customer(db)
    _subscribe_signed_in(client, tenant, card, customer)

    response = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": 2, "reason": "restock"},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    alert = db.query(models.RestockAlert).one()
    assert alert.notified_at is not None

    notes = _restock_notes(db)
    assert {note.channel for note in notes} == {"in_app", "push"}
    assert all(note.recipient is None for note in notes)
    assert all(note.user_id == customer.id for note in notes)
    in_app = next(note for note in notes if note.channel == "in_app")
    assert in_app.sent_at is not None
    assert in_app.payload["name"] == "Lightning Bolt"
    assert in_app.payload["price_minor"] == 125000

    rows = client.get("/v1/staff/stock", headers=auth).json()["items"]
    row = next(item for item in rows if item["stock_id"] == str(stock.id))
    assert row["restock_waiting"] == 0


def test_guest_subscribers_get_no_restock_updates(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)
    _subscribe(client, tenant, card)

    response = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": 2, "reason": "restock"},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    alert = db.query(models.RestockAlert).one()
    # Guests have no app account to notify and event email is reserved for
    # account security, so their alert stays pending rather than consumed.
    assert alert.customer_id is None
    assert alert.notified_at is None
    assert _restock_notes(db) == []


def test_no_notification_when_still_sold_out_or_offline(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)
    customer = _customer(db)
    _subscribe_signed_in(client, tenant, card, customer)

    still_zero = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": 0, "reason": "count check"},
        headers=auth,
    )
    assert still_zero.status_code == 200
    db.expire_all()
    assert db.query(models.RestockAlert).one().notified_at is None
    assert _restock_notes(db) == []

    stock.is_online = False
    db.commit()
    hidden = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": 2, "reason": "restock offline"},
        headers=auth,
    )
    assert hidden.status_code == 200
    db.expire_all()
    assert db.query(models.RestockAlert).one().notified_at is None


def test_turning_stock_back_online_triggers_restock_alerts(client, auth, tenant, card, stock, db):
    stock.quantity = 2
    stock.is_online = False
    db.commit()
    customer = _customer(db)
    _subscribe_signed_in(client, tenant, card, customer)

    response = client.patch(
        f"/v1/staff/stock/{stock.id}",
        json={"is_online": True},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    assert db.query(models.RestockAlert).one().notified_at is not None
    assert len(_restock_notes(db)) == 2


def test_releasing_a_reservation_triggers_restock_alerts(client, tenant, stock, reservation_payload, db):
    stock.quantity = 1
    stock.reserved = 0
    db.commit()
    reservation_payload["items"][0]["quantity"] = 1
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    body = created.json()
    customer = _customer(db)
    _subscribe_signed_in(client, tenant, stock.card, customer)

    cancelled = client.post(
        f"/v1/reservations/{body['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug, "X-Reservation-Token": body["access_token"]},
    )
    assert cancelled.status_code == 200, cancelled.text

    db.expire_all()
    assert db.query(models.RestockAlert).one().notified_at is not None
    assert len(_restock_notes(db)) == 2


def test_csv_import_triggers_restock_alerts(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)
    customer = _customer(db)
    _subscribe_signed_in(client, tenant, card, customer)

    body = (
        "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"
        "Lightning Bolt,LEB,161,nonfoil,NM,en,5,1250,RSD,true\n"
    )
    response = client.post(
        "/v1/staff/stock/import",
        files={"file": ("stock.csv", body.encode("utf-8"), "text/csv")},
        data={"dry_run": "false"},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    assert db.query(models.RestockAlert).one().notified_at is not None
    assert len(_restock_notes(db)) == 2


def test_unsubscribe_requires_the_matching_email(client, tenant, card, stock, db):
    alert = _subscribe(client, tenant, card).json()

    wrong = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}/unsubscribe",
        json={"email": "other@example.com"},
    )
    assert wrong.status_code == 204
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 1

    ok = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}/unsubscribe",
        json={"email": "READER@example.com"},
    )
    assert ok.status_code == 204
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 0

    again = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}/unsubscribe",
        json={"email": "reader@example.com"},
    )
    assert again.status_code == 204


def test_manage_token_unsubscribes_without_email(client, tenant, card, stock, db):
    alert = _subscribe(client, tenant, card).json()
    path = f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}/unsubscribe"

    bad = client.post(f"{path}?token=not-a-real-token")
    assert bad.status_code == 400
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 1

    # The human-facing link shows a confirmation page and does not mutate.
    page = client.get(f"{path}?token={alert['manage_token']}")
    assert page.status_code == 200
    assert "Unsubscribe from restock alerts" in page.text
    assert f'action="{path}/one-click?token={alert["manage_token"]}"' in page.text
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 1

    one_click = client.post(
        f"{path}/one-click?token={alert['manage_token']}",
        data={"List-Unsubscribe": "One-Click"},
    )
    assert one_click.status_code == 200
    assert "Unsubscribed" in one_click.text
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 0

    repeat = client.post(f"{path}/one-click?token={alert['manage_token']}")
    assert repeat.status_code == 200
    assert "Unsubscribed" in repeat.text


def test_invalid_unsubscribe_page_is_not_actionable(client, tenant, card, stock):
    response = client.get(
        f"/v1/shops/{tenant.slug}/restock-alerts/00000000-0000-0000-0000-000000000000/unsubscribe?token=bad"
    )
    assert response.status_code == 400
    assert "Invalid link" in response.text
    assert "<button" not in response.text


def test_unknown_card_is_rejected(client, tenant):
    response = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json={"email": "reader@example.com", "card_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
