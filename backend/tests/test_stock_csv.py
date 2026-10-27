from __future__ import annotations

import uuid

from app import models

HEADER = "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"


def _upload(client, auth, body: str, dry_run: bool):
    return client.post(
        "/v1/staff/stock/import",
        files={"file": ("stock.csv", body.encode("utf-8"), "text/csv")},
        data={"dry_run": "true" if dry_run else "false"},
        headers=auth,
    )


def _second_card(db) -> models.Card:
    card = models.Card(
        id=uuid.uuid4(),
        provider_card_id=f"scryfall-counterspell-{uuid.uuid4().hex[:6]}",
        name="Counterspell",
        set_code="LEB",
        set_name="Limited Edition Beta",
        collector_number="60",
        rarity="common",
        type_line="Instant",
        colors=["U"],
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


def test_export_uses_import_template(client, tenant, stock, auth):
    response = client.get("/v1/staff/stock/export.csv", headers=auth)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "stock-bolt-shop.csv" in response.headers["content-disposition"]

    lines = response.text.strip().splitlines()
    assert lines[0].split(",") == [
        "card_name",
        "set_code",
        "collector_number",
        "finish",
        "condition",
        "language",
        "quantity",
        "price",
        "currency",
        "is_online",
        "available",
    ]
    assert "Lightning Bolt,LEB,161,nonfoil,NM,en,3,1250.00,RSD,true,3" in lines[1]


def test_export_round_trips_as_unchanged(client, tenant, stock, auth):
    exported = client.get("/v1/staff/stock/export.csv", headers=auth).text
    report = _upload(client, auth, exported, dry_run=True)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["errors"] == []
    assert data["unchanged"] == 1
    assert data["created"] == 0
    assert data["updated"] == 0


def test_dry_run_reports_changes_without_writing(client, tenant, stock, auth, db):
    body = HEADER + "Lightning Bolt,LEB,161,nonfoil,NM,en,9,1300.00,RSD,false\n"
    report = _upload(client, auth, body, dry_run=True)
    assert report.status_code == 200
    data = report.json()
    assert data["dry_run"] is True
    assert data["updated"] == 1
    assert data["errors"] == []

    db.expire_all()
    unchanged = db.get(models.Stock, stock.id)
    assert unchanged is not None
    assert unchanged.quantity == 3
    assert unchanged.price_minor == 125000
    assert unchanged.is_online is True


def test_import_updates_and_records_a_movement(client, tenant, stock, auth, db):
    body = HEADER + "Lightning Bolt,LEB,161,nonfoil,NM,en,5,1300.00,RSD,false\n"
    report = _upload(client, auth, body, dry_run=False)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["dry_run"] is False
    assert data["updated"] == 1
    assert data["errors"] == []

    db.expire_all()
    updated = db.get(models.Stock, stock.id)
    assert updated is not None
    assert (updated.quantity, updated.price_minor, updated.is_online) == (5, 130000, False)

    movement = db.query(models.StockMovement).filter_by(stock_id=stock.id, kind="IMPORT").one()
    assert movement.on_hand_delta == 2
    assert movement.on_hand_after == 5


def test_import_creates_stock_for_a_catalog_card(client, tenant, auth, db):
    card = _second_card(db)
    body = HEADER + "Counterspell,LEB,60,foil,LP,en,2,450.00,RSD,true\n"
    report = _upload(client, auth, body, dry_run=False)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["created"] == 1
    assert data["errors"] == []

    created = db.query(models.Stock).filter_by(card_id=card.id, finish="foil", condition="LP").one()
    assert created.quantity == 2
    assert created.price_minor == 45000
    assert created.currency == "RSD"

    movement = db.query(models.StockMovement).filter_by(stock_id=created.id, kind="IMPORT").one()
    assert movement.on_hand_delta == 2


def test_unknown_catalog_card_is_reported_per_row(client, tenant, stock, auth, db):
    body = (
        HEADER
        + "Mystery Card,ZZZ,999,nonfoil,NM,en,1,100.00,RSD,true\n"
        + "Lightning Bolt,LEB,161,nonfoil,NM,en,4,1250.00,RSD,true\n"
    )
    report = _upload(client, auth, body, dry_run=False)
    data = report.json()
    assert data["updated"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["row"] == 2
    assert "No catalog card" in data["errors"][0]["message"]

    db.expire_all()
    assert db.get(models.Stock, stock.id).quantity == 4


def test_import_cannot_drop_below_reserved(client, tenant, stock, auth, reservation_payload, db):
    created = client.post(f"/v1/shops/{tenant.slug}/reservations", json=reservation_payload)
    assert created.status_code == 201

    body = HEADER + "Lightning Bolt,LEB,161,nonfoil,NM,en,1,1250.00,RSD,true\n"
    report = _upload(client, auth, body, dry_run=False)
    data = report.json()
    assert data["updated"] == 0
    assert len(data["errors"]) == 1
    assert "reserved" in data["errors"][0]["message"]

    db.expire_all()
    assert db.get(models.Stock, stock.id).quantity == 3


def test_conflicting_currency_is_rejected(client, tenant, stock, auth):
    body = HEADER + "Lightning Bolt,LEB,161,nonfoil,NM,en,3,10.00,EUR,true\n"
    data = _upload(client, auth, body, dry_run=True).json()
    assert data["errors"][0]["field"] == "currency"


def test_duplicate_rows_are_rejected(client, tenant, stock, auth):
    row = "Lightning Bolt,LEB,161,nonfoil,NM,en,3,1250.00,RSD,true\n"
    data = _upload(client, auth, HEADER + row + row, dry_run=True).json()
    assert len(data["errors"]) == 1
    assert "Duplicate" in data["errors"][0]["message"]


def test_missing_columns_is_a_400(client, auth):
    response = _upload(client, auth, "card_name,quantity\nLightning Bolt,3\n", dry_run=True)
    assert response.status_code == 400
    assert "Missing required column" in response.json()["detail"]


def test_bad_values_are_reported_per_field(client, tenant, stock, auth):
    body = HEADER + "Lightning Bolt,LEB,161,shiny,EX,en,three,12.345,RSD,maybe\n"
    data = _upload(client, auth, body, dry_run=True).json()
    fields = {error["field"] for error in data["errors"]}
    assert {"finish", "condition", "quantity", "price", "is_online"} <= fields
