from __future__ import annotations

from app import models


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

    second = _subscribe(client, tenant, card)
    assert second.status_code == 201
    assert second.json()["already_subscribed"] is True
    assert second.json()["id"] == first.json()["id"]

    rows = client.get("/v1/staff/stock", headers=auth).json()["items"]
    row = next(item for item in rows if item["stock_id"] == str(stock.id))
    assert row["restock_waiting"] == 1


def test_restock_notifies_waiting_customers_and_clears_the_count(client, auth, tenant, card, stock, db):
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
    assert alert.notified_at is not None

    note = (
        db.query(models.Notification)
        .filter_by(kind="RESTOCK_AVAILABLE")
        .order_by(models.Notification.id.desc())
        .first()
    )
    assert note is not None
    assert note.recipient == "reader@example.com"
    assert note.channel == "email"
    assert note.payload["name"] == "Lightning Bolt"
    assert note.payload["price_minor"] == 125000

    rows = client.get("/v1/staff/stock", headers=auth).json()["items"]
    row = next(item for item in rows if item["stock_id"] == str(stock.id))
    assert row["restock_waiting"] == 0


def test_no_notification_when_still_sold_out_or_offline(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)
    _subscribe(client, tenant, card)

    still_zero = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": 0, "reason": "count check"},
        headers=auth,
    )
    assert still_zero.status_code == 200
    db.expire_all()
    assert db.query(models.RestockAlert).one().notified_at is None
    assert db.query(models.Notification).filter_by(kind="RESTOCK_AVAILABLE").count() == 0

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


def test_csv_import_triggers_restock_alerts(client, auth, tenant, card, stock, db):
    _sold_out(db, stock)
    _subscribe(client, tenant, card)

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
    assert db.query(models.Notification).filter_by(kind="RESTOCK_AVAILABLE").count() == 1


def test_unsubscribe_requires_the_matching_email(client, tenant, card, stock, db):
    alert = _subscribe(client, tenant, card).json()

    wrong = client.delete(f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}?email=other@example.com")
    assert wrong.status_code == 204
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 1

    ok = client.delete(f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}?email=READER@example.com")
    assert ok.status_code == 204
    db.expire_all()
    assert db.query(models.RestockAlert).count() == 0

    again = client.delete(f"/v1/shops/{tenant.slug}/restock-alerts/{alert['id']}?email=reader@example.com")
    assert again.status_code == 204


def test_unknown_card_is_rejected(client, tenant):
    response = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json={"email": "reader@example.com", "card_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
