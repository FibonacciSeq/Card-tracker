from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import models
from app.services import reservations as reservation_service
from app.services import stock_archive
from app.services.reservations import ReservationError


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


def test_delete_one_archived_stock_removes_only_that_row(client, tenant, stock, second_stock, auth, db):
    stock_id = stock.id
    second_id = second_stock.id
    assert _archive(client, auth).status_code == 200

    deleted = client.delete(f"/v1/staff/stock/{second_id}", headers=auth)
    assert deleted.status_code == 204, deleted.text

    db.expire_all()
    assert db.get(models.Stock, second_id) is None
    assert db.get(models.Stock, stock_id) is not None
    archived = client.get("/v1/staff/stock?archived=true", headers=auth).json()["items"]
    assert [item["stock_id"] for item in archived] == [str(stock_id)]
    assert db.query(models.StockMovement).filter_by(stock_id=second_id).count() == 0
    assert db.query(models.AuditEvent).filter_by(action="stock.delete").count() == 1


def test_delete_one_rejects_active_and_missing_stock(client, stock, auth):
    active = client.delete(f"/v1/staff/stock/{stock.id}", headers=auth)
    assert active.status_code == 409
    assert "Only archived stock" in active.json()["detail"]

    assert _archive(client, auth).status_code == 200
    assert client.delete(f"/v1/staff/stock/{stock.id}", headers=auth).status_code == 204
    assert client.delete(f"/v1/staff/stock/{stock.id}", headers=auth).status_code == 404


def test_delete_one_rejects_reserved_archived_stock(client, tenant, stock, reservation_payload, auth):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    assert _archive(client, auth).status_code == 200

    response = client.delete(f"/v1/staff/stock/{stock.id}", headers=auth)
    assert response.status_code == 409
    assert "customer holds" in response.json()["detail"]


def test_delete_archive_keeps_rows_with_active_holds(
    client, tenant, stock, second_stock, reservation_payload, auth, db
):
    stock_id = stock.id
    second_id = second_stock.id
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    assert _archive(client, auth).status_code == 200

    response = client.delete("/v1/staff/stock/archive", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 1, "kept": 1}

    db.expire_all()
    assert db.get(models.Stock, second_id) is None
    assert db.get(models.Stock, stock_id).reserved == 2
    assert db.query(models.AuditEvent).filter_by(action="stock.delete_all").count() == 1


def test_delete_archive_never_touches_active_stock_or_another_shop(
    client, tenant, other_tenant, stock, second_stock, auth, db
):
    foreign = models.Stock(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        card_id=stock.card_id,
        finish="nonfoil",
        condition="NM",
        language="en",
        quantity=1,
        reserved=0,
        price_minor=1000,
        currency="RSD",
        archived_at=datetime.now(UTC),
    )
    db.add(foreign)
    db.commit()
    assert _archive(client, auth).status_code == 200

    response = client.delete("/v1/staff/stock/archive", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 2, "kept": 0}

    db.expire_all()
    assert db.query(models.Stock).filter_by(tenant_id=tenant.id).count() == 0
    assert db.get(models.Stock, foreign.id) is not None


def test_deleting_archived_stock_preserves_reservation_history(client, tenant, stock, reservation_payload, auth, db):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    reservation = created.json()
    cancelled = client.post(
        f"/v1/reservations/{reservation['id']}/cancel",
        headers={"X-Shop-Slug": tenant.slug, "X-Reservation-Token": reservation["access_token"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert _archive(client, auth).status_code == 200

    assert client.delete(f"/v1/staff/stock/{stock.id}", headers=auth).status_code == 204

    db.expire_all()
    line = db.query(models.ReservationLine).one()
    assert line.stock_id is None
    assert line.name == "Lightning Bolt"
    assert line.completed_quantity == 0
    assert line.cancelled_quantity == 2

    detail = client.get(f"/v1/staff/reservations/{reservation['id']}", headers=auth)
    assert detail.status_code == 200, detail.text
    assert detail.json()["lines"][0]["stock_id"] is None
    assert detail.json()["lines"][0]["name"] == "Lightning Bolt"


def test_archive_retention_setting_round_trips_and_validates(client, auth):
    settings = client.get("/v1/staff/settings", headers=auth)
    assert settings.status_code == 200
    assert settings.json()["archive_retention_days"] == 0

    saved = client.patch("/v1/staff/settings", headers=auth, json={"archive_retention_days": 45})
    assert saved.status_code == 200, saved.text
    assert saved.json()["archive_retention_days"] == 45

    assert client.patch("/v1/staff/settings", headers=auth, json={"archive_retention_days": -1}).status_code == 422
    assert client.patch("/v1/staff/settings", headers=auth, json={"archive_retention_days": 3651}).status_code == 422


def test_purge_deletes_only_expired_unheld_archived_stock(client, tenant, stock, second_stock, db):
    stock_id = stock.id
    second_id = second_stock.id
    now = datetime.now(UTC)
    tenant.settings.archive_retention_days = 30
    stock.archived_at = now - timedelta(days=31)
    second_stock.archived_at = now - timedelta(days=3)
    db.commit()

    assert stock_archive.purge_expired_archived_stock(db, now) == 1

    db.expire_all()
    assert db.get(models.Stock, stock_id) is None
    assert db.get(models.Stock, second_id) is not None
    assert db.query(models.AuditEvent).filter_by(action="stock.delete_expired").count() == 1


def test_purge_respects_retention_zero_and_active_holds(client, tenant, stock, reservation_payload, db):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text
    now = datetime.now(UTC)
    stock.archived_at = now - timedelta(days=500)
    tenant.settings.archive_retention_days = 0
    db.commit()
    assert stock_archive.purge_expired_archived_stock(db, now) == 0

    tenant.settings.archive_retention_days = 30
    db.commit()
    assert stock_archive.purge_expired_archived_stock(db, now) == 0

    db.expire_all()
    assert db.get(models.Stock, stock.id) is not None


def test_listing_archived_stock_purges_expired_rows_lazily(client, tenant, stock, second_stock, auth, db):
    stock_id = stock.id
    second_id = second_stock.id
    assert _archive(client, auth).status_code == 200
    tenant.settings.archive_retention_days = 30
    stock.archived_at = datetime.now(UTC) - timedelta(days=31)
    second_stock.archived_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()

    items = client.get("/v1/staff/stock?archived=true", headers=auth).json()["items"]
    assert [item["stock_id"] for item in items] == [str(second_id)]

    db.expire_all()
    assert db.get(models.Stock, stock_id) is None
    assert db.get(models.Stock, second_id) is not None


def _detached_open_reservation(db, tenant, stock):
    now = datetime.now(UTC)
    row = models.Reservation(
        tenant_id=tenant.id,
        public_ref=f"REF-{uuid.uuid4().hex[:8]}",
        customer_name="Ana Ilic",
        email="ana@example.com",
        status="CONFIRMED",
        total_minor=1000,
        currency="RSD",
        expires_at=now - timedelta(minutes=1),
    )
    row.lines.append(
        models.ReservationLine(
            tenant_id=tenant.id,
            stock_id=None,
            card_id=stock.card_id,
            name="Lightning Bolt",
            set_code="LEB",
            collector_number="161",
            finish="nonfoil",
            condition="NM",
            language="en",
            quantity=1,
            unit_price_minor=1000,
            currency="RSD",
        )
    )
    db.add(row)
    db.commit()
    return row


def test_delete_empty_archive_is_a_noop(client, auth, db):
    response = client.delete("/v1/staff/stock/archive", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 0, "kept": 0}
    assert db.query(models.AuditEvent).filter_by(action="stock.delete_all").count() == 0


def test_expiring_a_reservation_whose_stock_row_is_missing_fails_safely(db, tenant, stock):
    row = _detached_open_reservation(db, tenant, stock)

    with pytest.raises(ReservationError):
        reservation_service.expire_due_reservations(db)

    db.expire_all()
    assert db.get(models.Reservation, row.id).status == "CONFIRMED"


def test_completing_a_reservation_whose_stock_row_is_missing_fails_safely(db, tenant, stock):
    row = _detached_open_reservation(db, tenant, stock)

    with pytest.raises(ReservationError):
        reservation_service.complete_reservation(db, row)

    db.expire_all()
    assert db.get(models.Reservation, row.id).status == "CONFIRMED"
