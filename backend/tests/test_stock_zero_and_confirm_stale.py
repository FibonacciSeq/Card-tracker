from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import models

CSV_HEADER = "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"


def _stock_ids(response) -> list[str]:
    return [item["stock_id"] for item in response.json()["items"]]


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _assert_hidden_from_customers(client, tenant, stock):
    listed = client.get(f"/v1/shops/{tenant.slug}/stock")
    assert listed.status_code == 200
    assert stock.id not in {uuid.UUID(item["stock_id"]) for item in listed.json()["items"]}

    detail = client.get(f"/v1/shops/{tenant.slug}/stock/{stock.id}")
    assert detail.status_code == 404

    facets = client.get(f"/v1/shops/{tenant.slug}/facets").json()
    assert stock.finish not in [item["value"] for item in facets["finishes"]]


def test_selling_last_copy_archives_and_hides_it(client, tenant, stock, auth, db):
    response = client.post(
        f"/v1/staff/stock/{stock.id}/sell",
        json={"quantity": 3},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["archived_at"] is not None

    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None and row.quantity == 0 and row.archived_at is not None

    assert _stock_ids(client.get("/v1/staff/stock", headers=auth)) == []
    assert _stock_ids(client.get("/v1/staff/stock?archived=true", headers=auth)) == [str(stock.id)]
    _assert_hidden_from_customers(client, tenant, stock)


def test_adjusting_to_zero_archives_and_hides_it(client, tenant, stock, auth, db):
    response = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        json={"delta": -3, "reason": "shelf count"},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None
    assert _stock_ids(client.get("/v1/staff/stock", headers=auth)) == []
    _assert_hidden_from_customers(client, tenant, stock)


def test_setting_quantity_to_zero_archives_and_hides_it(client, tenant, stock, auth, db):
    response = client.patch(
        f"/v1/staff/stock/{stock.id}",
        json={"quantity": 0},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None
    _assert_hidden_from_customers(client, tenant, stock)


def test_completing_reservation_for_last_copy_archives_it(client, tenant, stock, reservation_payload, auth, db):
    reservation_payload["items"][0]["quantity"] = 3
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201, created.text

    response = client.post(f"/v1/staff/reservations/{created.json()['id']}/complete", json={}, headers=auth)
    assert response.status_code == 200, response.text

    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None and row.quantity == 0 and row.archived_at is not None
    _assert_hidden_from_customers(client, tenant, stock)


def test_zero_quantity_csv_import_archives_the_row(client, tenant, stock, auth, db):
    body = CSV_HEADER + "Lightning Bolt,LEB,161,nonfoil,NM,en,0,1250.00,RSD,true\n"
    response = client.post(
        "/v1/staff/stock/import",
        files={"file": ("stock.csv", body.encode("utf-8"), "text/csv")},
        data={"dry_run": "false"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 1

    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None
    _assert_hidden_from_customers(client, tenant, stock)


def test_creating_empty_stock_archives_it(client, tenant, card, auth, db):
    response = client.post(
        "/v1/staff/stock",
        json={
            "card_id": str(card.id),
            "finish": "foil",
            "condition": "NM",
            "language": "en",
            "quantity": 0,
            "price_minor": 100,
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    created_id = uuid.UUID(response.json()["stock_id"])
    assert response.json()["archived_at"] is not None
    assert created_id not in {
        uuid.UUID(item["stock_id"]) for item in client.get("/v1/staff/stock", headers=auth).json()["items"]
    }


def test_restore_empty_stock_requires_a_quantity(client, tenant, stock, auth, db):
    sold = client.post(f"/v1/staff/stock/{stock.id}/sell", json={"quantity": 3}, headers=auth)
    assert sold.status_code == 200
    db.expire_all()
    assert db.get(models.Stock, stock.id).archived_at is not None

    missing = client.post(f"/v1/staff/stock/{stock.id}/restore", json={}, headers=auth)
    assert missing.status_code == 409
    assert "quantity" in missing.json()["detail"]

    zero = client.post(f"/v1/staff/stock/{stock.id}/restore", json={"quantity": 0}, headers=auth)
    assert zero.status_code == 409

    restored = client.post(f"/v1/staff/stock/{stock.id}/restore", json={"quantity": 2}, headers=auth)
    assert restored.status_code == 200, restored.text
    assert restored.json()["on_hand"] == 2
    assert restored.json()["archived_at"] is None

    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None and row.quantity == 2 and row.archived_at is None

    movement = db.query(models.StockMovement).filter_by(stock_id=stock.id, reason="restored with quantity").one()
    assert movement.on_hand_delta == 2


def test_restore_nonempty_stock_still_works_without_a_quantity(client, stock, auth, db):
    stock.archived_at = datetime.now(UTC)
    db.commit()

    response = client.post(f"/v1/staff/stock/{stock.id}/restore", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["archived_at"] is None


def test_legacy_zero_row_is_hidden_even_without_archiving(client, tenant, card, db):
    row = models.Stock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        card_id=card.id,
        finish="foil",
        condition="NM",
        language="en",
        quantity=0,
        price_minor=100,
        currency=tenant.currency,
        is_online=True,
    )
    db.add(row)
    db.commit()

    _assert_hidden_from_customers(client, tenant, row)


def test_confirm_all_stale_only_touches_stale_online_nonempty_stock(
    client, tenant, stock, second_stock, auth, db, other_tenant
):
    old = datetime.now(UTC) - timedelta(days=8)
    stock.updated_at = old
    second_stock.updated_at = old
    second_stock.is_online = False
    empty = models.Stock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        card_id=stock.card_id,
        finish="foil",
        condition="LP",
        language="en",
        quantity=0,
        price_minor=100,
        currency=tenant.currency,
        is_online=True,
    )
    empty.updated_at = old
    archived = models.Stock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        card_id=stock.card_id,
        finish="foil",
        condition="HP",
        language="en",
        quantity=2,
        price_minor=100,
        currency=tenant.currency,
        is_online=True,
        archived_at=old,
    )
    archived.updated_at = old
    other = models.Stock(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        card_id=stock.card_id,
        finish="etched",
        condition="NM",
        language="en",
        quantity=2,
        price_minor=100,
        currency=other_tenant.currency,
        is_online=True,
    )
    other.updated_at = old
    db.add_all([empty, archived, other])
    db.commit()

    response = client.post("/v1/staff/stock/confirm-stale", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"confirmed": 1}

    db.expire_all()
    assert _as_utc(db.get(models.Stock, stock.id).updated_at) > old
    assert _as_utc(db.get(models.Stock, second_stock.id).updated_at) == old
    assert _as_utc(db.get(models.Stock, empty.id).updated_at) == old
    assert _as_utc(db.get(models.Stock, archived.id).updated_at) == old
    assert _as_utc(db.get(models.Stock, other.id).updated_at) == old

    assert client.get("/v1/staff/stock?stale=true", headers=auth).json()["items"] == []
    events = client.get("/v1/staff/audit?action=stock.confirm_all", headers=auth).json()
    assert len(events) == 1
    assert events[0]["data"] == {"confirmed": 1}


def test_confirm_all_stale_with_nothing_to_do(client, stock, auth):
    response = client.post("/v1/staff/stock/confirm-stale", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"confirmed": 0}
    assert client.get("/v1/staff/audit?action=stock.confirm_all", headers=auth).json() == []
