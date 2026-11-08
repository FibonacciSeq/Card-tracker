from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import models


def _archive(client, auth):
    return client.post("/v1/staff/stock/archive", headers=auth)


def _public_items(client, tenant):
    response = client.get(f"/v1/shops/{tenant.slug}/stock?limit=50")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _import(client, auth, body: str, *, dry_run: bool):
    return client.post(
        "/v1/staff/stock/import",
        files={"file": ("stock.csv", body.encode("utf-8"), "text/csv")},
        data={"dry_run": "true" if dry_run else "false"},
        headers=auth,
    )


def test_archive_all_moves_stock_out_of_the_active_and_public_lists(client, tenant, stock, second_stock, auth, db):
    response = _archive(client, auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"archived": 2, "reserved": 0}

    assert client.get("/v1/staff/stock", headers=auth).json()["items"] == []
    archived = client.get("/v1/staff/stock?archived=true", headers=auth).json()["items"]
    assert {item["stock_id"] for item in archived} == {str(stock.id), str(second_stock.id)}
    assert all(item["archived_at"] for item in archived)

    assert _public_items(client, tenant) == []
    assert client.get(f"/v1/shops/{tenant.slug}/facets").json()["finishes"] == []
    assert client.get(f"/v1/shops/{tenant.slug}/stock/{stock.id}").status_code == 404

    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None
    assert db.get(models.Stock, second_stock.id).archived_at is not None

    events = client.get("/v1/staff/audit?action=stock.archive_all", headers=auth).json()
    assert events and events[0]["summary"] == "Archived all stock (2 rows)"

    # Archiving again is a no-op rather than an error.
    again = _archive(client, auth)
    assert again.status_code == 200
    assert again.json() == {"archived": 0, "reserved": 0}


def test_archive_all_is_scoped_to_the_current_shop(client, tenant, other_tenant, card, stock, auth, db):
    other = models.Stock(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        card_id=card.id,
        finish="nonfoil",
        condition="NM",
        language="en",
        quantity=2,
        price_minor=5000,
        currency="RSD",
        is_online=True,
    )
    db.add(other)
    db.commit()

    assert _archive(client, auth).status_code == 200

    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None
    assert db.get(models.Stock, other.id).archived_at is None


def test_archive_all_reports_reserved_copies_and_keeps_reservations_working(
    client, tenant, stock, reservation_payload, auth, db
):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text

    archived = _archive(client, auth)
    assert archived.status_code == 200
    assert archived.json() == {"archived": 1, "reserved": 2}

    completed = client.post(
        f"/v1/staff/reservations/{created.json()['id']}/complete",
        json={},
        headers=auth,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"

    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None
    assert row.archived_at is not None
    assert row.quantity == 1
    assert row.reserved == 0


def test_archived_stock_blocks_new_holds_and_edits_then_restores(client, tenant, stock, reservation_payload, auth, db):
    assert _archive(client, auth).status_code == 200

    blocked = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert blocked.status_code == 404
    assert "no longer" in blocked.json()["detail"]

    for method, path, payload in (
        ("patch", f"/v1/staff/stock/{stock.id}", {"quantity": 1}),
        ("post", f"/v1/staff/stock/{stock.id}/adjust", {"delta": 1}),
        ("post", f"/v1/staff/stock/{stock.id}/sell", {"quantity": 1}),
    ):
        response = getattr(client, method)(path, json=payload, headers=auth)
        assert response.status_code == 409, response.text
        assert "Archived" in response.json()["detail"]

    restored = client.post(f"/v1/staff/stock/{stock.id}/restore", headers=auth)
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    assert restored.json()["is_online"] is True

    edited = client.patch(f"/v1/staff/stock/{stock.id}", json={"quantity": 4}, headers=auth)
    assert edited.status_code == 200, edited.text
    assert edited.json()["on_hand"] == 4

    # Restoring an active row is harmless and returns it unchanged.
    again = client.post(f"/v1/staff/stock/{stock.id}/restore", headers=auth)
    assert again.status_code == 200
    assert again.json()["archived_at"] is None


def test_create_stock_restores_an_archived_variant(client, tenant, stock, auth, db):
    assert _archive(client, auth).status_code == 200

    response = client.post(
        "/v1/staff/stock",
        json={
            "card_id": str(stock.card_id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
            "quantity": 5,
            "price_minor": 200000,
            "currency": "RSD",
            "is_online": True,
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stock_id"] == str(stock.id)
    assert body["archived_at"] is None
    assert body["on_hand"] == 5
    assert body["available"] == 5

    # Re-posting an active variant now conflicts.
    conflict = client.post(
        "/v1/staff/stock",
        json={
            "card_id": str(stock.card_id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
            "quantity": 1,
            "price_minor": 100,
            "currency": "RSD",
        },
        headers=auth,
    )
    assert conflict.status_code == 409

    # Restoring with the same quantity does not create an extra movement.
    assert _archive(client, auth).status_code == 200
    same = client.post(
        "/v1/staff/stock",
        json={
            "card_id": str(stock.card_id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
            "quantity": 5,
            "price_minor": 200000,
            "currency": "RSD",
            "is_online": True,
        },
        headers=auth,
    )
    assert same.status_code == 201, same.text
    db.expire_all()
    movements = db.query(models.StockMovement).filter_by(stock_id=stock.id, reason="restored archived stock").all()
    assert len(movements) == 1
    assert movements[0].on_hand_delta == 2


def test_create_stock_cannot_restore_below_reserved(client, tenant, stock, reservation_payload, auth):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    assert _archive(client, auth).status_code == 200

    response = client.post(
        "/v1/staff/stock",
        json={
            "card_id": str(stock.card_id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
            "quantity": 1,
            "price_minor": 100,
            "currency": "RSD",
        },
        headers=auth,
    )
    assert response.status_code == 409
    assert "reserved" in response.json()["detail"]


def test_csv_import_restores_archived_rows(client, tenant, stock, auth, db):
    assert _archive(client, auth).status_code == 200
    body = (
        "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"
        "Lightning Bolt,LEB,161,nonfoil,NM,en,5,1250.00,RSD,true\n"
    )

    dry = _import(client, auth, body, dry_run=True)
    assert dry.status_code == 200, dry.text
    assert dry.json()["updated"] == 1
    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None

    applied = _import(client, auth, body, dry_run=False)
    assert applied.status_code == 200, applied.text
    assert applied.json()["updated"] == 1
    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None
    assert row.archived_at is None
    assert row.quantity == 5
    assert _public_items(client, tenant)

    # A matching row with identical values is still restored, not reported unchanged.
    assert _archive(client, auth).status_code == 200
    same = _import(client, auth, body, dry_run=False)
    assert same.status_code == 200, same.text
    assert same.json()["updated"] == 1
    assert same.json()["unchanged"] == 0
    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is None


def test_export_excludes_archived_stock_by_default(client, tenant, stock, auth):
    assert _archive(client, auth).status_code == 200

    active = client.get("/v1/staff/stock/export.csv", headers=auth)
    assert active.status_code == 200
    assert "Lightning Bolt" not in active.text
    assert active.headers["content-disposition"].endswith('filename="stock-bolt-shop.csv"')

    archived = client.get("/v1/staff/stock/export.csv?archived=true", headers=auth)
    assert archived.status_code == 200
    assert "Lightning Bolt" in archived.text
    assert archived.headers["content-disposition"].endswith('filename="stock-bolt-shop-archived.csv"')


def test_archived_stock_is_excluded_from_dashboard_attention_counts(client, tenant, stock, auth, db):
    stock.quantity = 1
    stock.updated_at = datetime.now(UTC) - timedelta(days=8)
    db.commit()

    before = client.get("/v1/staff/dashboard", headers=auth).json()
    assert before["low_stock"] == 1
    assert before["stale_stock"] == 1

    assert _archive(client, auth).status_code == 200

    after = client.get("/v1/staff/dashboard", headers=auth).json()
    assert after["low_stock"] == 0
    assert after["stale_stock"] == 0


def test_repricing_skips_archived_stock(client, tenant, stock, card, auth, db, monkeypatch):
    card.scryfall_prices = {"usd": "2.00"}
    db.commit()
    assert _archive(client, auth).status_code == 200

    response = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={
            "scryfall_pricing_enabled": True,
            "scryfall_min_price_minor": 10_000,
            "scryfall_markup_percent": 10,
        },
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None
    assert row.price_minor == 125000
    assert response.json()["repriced_stock"] == 0


def test_archived_stock_cannot_be_converted_from_a_card_request(client, tenant, card, stock, auth):
    created = client.post(
        f"/v1/shops/{tenant.slug}/card-requests",
        json={
            "customer": {"name": "Ana Ilic", "email": "ana@example.com", "phone": "+38160111222"},
            "card_id": str(card.id),
            "requested_name": "",
            "quantity": 2,
            "target_price_minor": 300000,
        },
    )
    assert created.status_code == 201, created.text
    request = created.json()
    quoted = client.post(
        f"/v1/staff/card-requests/{request['id']}/quote",
        headers=auth,
        json={"quote_price_minor": 275000},
    )
    assert quoted.status_code == 200, quoted.text
    accepted = client.post(
        f"/v1/card-requests/{request['id']}/accept",
        headers={"X-Shop-Slug": tenant.slug, "X-Card-Request-Token": request["access_token"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert _archive(client, auth).status_code == 200

    converted = client.post(f"/v1/staff/card-requests/{request['id']}/convert", headers=auth, json={})
    assert converted.status_code == 409
    assert "Add this exact card and variant" in converted.json()["detail"]


def test_archived_stock_does_not_fire_restock_alerts_when_a_hold_is_released(
    client, tenant, stock, reservation_payload, auth, db
):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    body = created.json()

    subscribed = client.post(
        f"/v1/shops/{tenant.slug}/restock-alerts",
        json={
            "email": "waiting@example.com",
            "card_id": str(stock.card_id),
            "finish": "nonfoil",
            "condition": "NM",
            "language": "en",
        },
    )
    assert subscribed.status_code == 201, subscribed.text
    assert _archive(client, auth).status_code == 200

    cancelled = client.post(
        f"/v1/reservations/{body['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug, "X-Reservation-Token": body["access_token"]},
    )
    assert cancelled.status_code == 200, cancelled.text

    db.expire_all()
    alert = db.query(models.RestockAlert).one()
    assert alert.notified_at is None
    assert db.query(models.Notification).filter_by(kind="RESTOCK_AVAILABLE").count() == 0
