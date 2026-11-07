from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app import models
from app.services import exchange_rates, scryfall_pricing, stock_csv

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


def test_manabox_csv_headers_and_values_are_normalized():
    body = (
        "Name,Set code,Set name,Collector number,Foil,Rarity,Quantity,"
        "ManaBox ID,Scryfall ID,Purchase price,Misprint,Altered,Signed,"
        "Condition,Language,Proxy,Purchase price currency,Added\n"
        "Lightning Bolt,LEB,Limited Edition Beta,161,normal,common,3,"
        "123,card-id,12.50,false,false,false,near_mint,en,false,EUR,2026-01-01\n"
        "Lightning Bolt,LEB,Limited Edition Beta,161,foil,common,1,"
        "123,card-id,20.00,false,false,false,near_mint,en,false,EUR,2026-01-01\n"
    )

    rows, errors = stock_csv.parse_csv(body, "EUR")
    assert errors == []
    assert [(row.finish, row.condition, row.quantity, row.price_minor) for row in rows] == [
        ("nonfoil", "NM", 3, 1250),
        ("foil", "NM", 1, 2000),
    ]
    assert all(row.uses_pricing_rules for row in rows)

    rows, errors = stock_csv.parse_csv(body, "RSD")
    assert errors == []
    rules = {"threshold_minor": 1_500, "fixed_price_minor": 15_000, "markup_percent": 20}
    priced = stock_csv.price_purchase_rows(rows, "RSD", {"EUR": Decimal("1")}, rules)
    assert {row.currency for row in priced} == {"RSD"}
    assert [row.price_minor for row in priced] == [15_000, 3_000]


def test_markup_prices_equal_threshold_and_rounds_strictly_up():
    rules = {"threshold_minor": 10_000, "fixed_price_minor": 15_000, "markup_percent": 10}
    assert stock_csv.calculate_sale_price(9_999, Decimal("1"), rules) == 15_000
    assert stock_csv.calculate_sale_price(10_000, Decimal("1"), rules) == 12_000


def test_scryfall_price_floor_and_threshold_markup():
    rules = {"minimum_price_minor": 10_000, "markup_percent": 10, "rounding_increment_minor": 100}
    assert scryfall_pricing.calculate_sale_price(Decimal("0.99"), "USD", "RSD", rules, Decimal("100")) == 10_000
    assert scryfall_pricing.calculate_sale_price(Decimal("1.00"), "USD", "RSD", rules, Decimal("100")) == 11_100


def test_purchase_price_csv_requires_pricing_rules(client, auth):
    body = (
        "Name,Set code,Collector number,Foil,Quantity,Purchase price,Condition,"
        "Language,Purchase price currency\n"
        "Lightning Bolt,LEB,161,normal,3,1.00,near_mint,en,EUR\n"
    )
    response = _upload(client, auth, body, dry_run=True)
    assert response.status_code == 409
    assert "pricing rules" in response.json()["detail"]


def test_legacy_pricing_endpoint_creates_settings_and_reports_configuration(client, tenant, auth, db):
    tenant.settings = None
    db.commit()
    initial = client.get("/v1/staff/stock/import-pricing", headers=auth)
    assert initial.status_code == 200
    assert initial.json()["configured"] is False

    updated = client.patch(
        "/v1/staff/stock/import-pricing",
        headers=auth,
        json={"threshold_minor": 1_000, "fixed_price_minor": 2_000, "markup_percent": 20},
    )
    assert updated.status_code == 200
    assert updated.json()["configured"] is True
    assert client.get("/v1/staff/stock/import-pricing", headers=auth).json()["markup_percent"] == 20


@pytest.mark.parametrize(
    ("failure", "status_code"),
    [
        (exchange_rates.ExchangeRateError("rate unavailable"), 503),
        (ValueError("price overflow"), 422),
    ],
)
def test_scryfall_import_surfaces_pricing_failures(client, tenant, auth, db, monkeypatch, failure, status_code):
    tenant.settings.scryfall_pricing = {
        "enabled": True,
        "minimum_price_minor": 1_000,
        "markup_percent": 10,
    }
    db.commit()

    def fail(*_args):
        raise failure

    monkeypatch.setattr("app.services.scryfall_pricing.price_import_rows", fail)
    body = HEADER + "Lightning Bolt,LEB,161,nonfoil,NM,en,1,1.00,RSD,true\n"
    response = _upload(client, auth, body, dry_run=True)
    assert response.status_code == status_code


@pytest.mark.parametrize(
    ("failure", "status_code"),
    [
        (exchange_rates.ExchangeRateError("rate unavailable"), 503),
        (ValueError("price overflow"), 422),
    ],
)
def test_legacy_purchase_price_import_surfaces_pricing_failures(
    client, tenant, auth, db, monkeypatch, failure, status_code
):
    tenant.settings.stock_import_pricing = {
        "threshold_minor": 1_000,
        "fixed_price_minor": 2_000,
        "markup_percent": 10,
    }
    db.commit()
    body = (
        "Name,Set code,Collector number,Foil,Quantity,Purchase price,Condition,"
        "Language,Purchase price currency\n"
        "Lightning Bolt,LEB,161,normal,1,1.00,near_mint,en,EUR\n"
    )
    if isinstance(failure, exchange_rates.ExchangeRateError):
        monkeypatch.setattr("app.api.staff.exchange_rate_service.get_latest_rate", lambda *_args: _raise(failure))
    else:
        monkeypatch.setattr(
            "app.api.staff.exchange_rate_service.get_latest_rate",
            lambda *_args: exchange_rates.ExchangeRate("EUR", "RSD", Decimal("1"), date(2026, 11, 6)),
        )
        monkeypatch.setattr("app.api.staff.stock_csv.price_purchase_rows", lambda *_args: _raise(failure))

    response = _upload(client, auth, body, dry_run=True)
    assert response.status_code == status_code


def _raise(error):
    raise error


def test_scryfall_pricing_settings_reprice_from_market_not_current_sale_price(
    client, tenant, stock, card, auth, db, monkeypatch
):
    card.scryfall_prices = {"usd": "2.00"}
    db.commit()
    monkeypatch.setattr(
        "app.services.scryfall_pricing.exchange_rates.get_latest_rate",
        lambda source, target: exchange_rates.ExchangeRate(source, target, Decimal("100"), date(2026, 11, 6)),
    )

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
    assert response.json()["scryfall_pricing_enabled"] is True

    db.expire_all()
    updated = db.get(models.Stock, stock.id)
    assert updated is not None
    assert updated.price_minor == 22_500
    assert response.json()["scryfall_rounding_increment"] == 5


def test_scryfall_rounding_increment_change_reprices_existing_stock(client, tenant, stock, card, auth, db, monkeypatch):
    card.scryfall_prices = {"usd": "2.00"}
    tenant.currency = "RSD"
    db.commit()
    monkeypatch.setattr(
        "app.services.scryfall_pricing.exchange_rates.get_latest_rate",
        lambda source, target: exchange_rates.ExchangeRate(source, target, Decimal("100"), date(2026, 11, 6)),
    )
    initial = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={
            "scryfall_pricing_enabled": True,
            "scryfall_min_price_minor": 1_000,
            "scryfall_markup_percent": 10,
            "scryfall_rounding_increment": 5,
        },
    )
    assert initial.status_code == 200, initial.text

    updated = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={"scryfall_rounding_increment": 10},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["scryfall_rounding_increment"] == 10
    assert updated.json()["repriced_stock"] == 1

    db.expire_all()
    assert db.get(models.Stock, stock.id).price_minor == 23_000


def test_scryfall_pricing_settings_reports_stock_without_market_data(client, tenant, stock, auth):
    response = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={
            "scryfall_pricing_enabled": True,
            "scryfall_min_price_minor": 1_000,
            "scryfall_markup_percent": 10,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["repriced_stock"] == 0
    assert response.json()["stock_without_scryfall_prices"] == 1


def test_scryfall_pricing_settings_accepts_partial_disable(client, tenant, auth):
    response = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={"scryfall_pricing_enabled": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["scryfall_pricing_enabled"] is False

    updated = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={"scryfall_min_price_minor": 1_500},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["scryfall_min_price_minor"] == 1_500


def test_scryfall_pricing_settings_rejects_enabling_without_required_values(client, tenant, auth, db):
    tenant.settings.scryfall_pricing = {
        "enabled": False,
        "minimum_price_minor": "invalid",
        "markup_percent": 0,
    }
    db.commit()
    response = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={"scryfall_pricing_enabled": True},
    )
    assert response.status_code == 422
    assert "minimum price and markup" in response.json()["detail"]


@pytest.mark.parametrize(
    ("failure", "status_code"),
    [
        (exchange_rates.ExchangeRateError("rate unavailable"), 503),
        (ValueError("price overflow"), 422),
    ],
)
def test_scryfall_pricing_settings_surfaces_repricing_failures(client, tenant, auth, monkeypatch, failure, status_code):
    def fail(*_args):
        raise failure

    monkeypatch.setattr("app.services.scryfall_pricing.reprice_tenant_stock", fail)
    response = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={
            "scryfall_pricing_enabled": True,
            "scryfall_min_price_minor": 1_000,
            "scryfall_markup_percent": 10,
        },
    )
    assert response.status_code == status_code


def test_scryfall_pricing_import_uses_finish_market_price_and_skips_missing(
    client, tenant, stock, card, auth, db, monkeypatch
):
    card.scryfall_prices = {"usd": "2.00"}
    db.commit()
    monkeypatch.setattr(
        "app.services.scryfall_pricing.exchange_rates.get_latest_rate",
        lambda source, target: exchange_rates.ExchangeRate(source, target, Decimal("100"), date(2026, 11, 6)),
    )
    saved = client.patch(
        "/v1/staff/settings",
        headers=auth,
        json={
            "scryfall_pricing_enabled": True,
            "scryfall_min_price_minor": 10_000,
            "scryfall_markup_percent": 10,
        },
    )
    assert saved.status_code == 200, saved.text

    body = (
        HEADER
        + "Lightning Bolt,LEB,161,nonfoil,NM,en,5,1250.00,RSD,true\n"
        + "Lightning Bolt,LEB,161,foil,NM,en,1,1250.00,RSD,true\n"
    )
    report = _upload(client, auth, body, dry_run=False)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["updated"] == 1
    assert len(data["errors"]) == 1
    assert "No Scryfall market price" in data["errors"][0]["message"]

    db.expire_all()
    assert db.get(models.Stock, stock.id).price_minor == 22_500


def test_purchase_price_import_applies_rules_and_daily_rate(client, tenant, stock, auth, monkeypatch):
    saved = client.patch(
        "/v1/staff/stock/import-pricing",
        headers=auth,
        json={"threshold_minor": 10_000, "fixed_price_minor": 15_000, "markup_percent": 10},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "currency": "RSD",
        "configured": True,
        "threshold_minor": 10_000,
        "fixed_price_minor": 15_000,
        "markup_percent": 10,
    }

    monkeypatch.setattr(
        "app.api.staff.exchange_rate_service.get_latest_rate",
        lambda source, target: exchange_rates.ExchangeRate(source, target, Decimal("100"), date(2026, 11, 6)),
    )
    body = (
        "Name,Set code,Collector number,Foil,Quantity,Purchase price,Condition,"
        "Language,Purchase price currency\n"
        "Lightning Bolt,LEB,161,normal,3,1.00,near_mint,en,EUR\n"
    )
    report = _upload(client, auth, body, dry_run=False)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["updated"] == 1
    assert data["errors"] == []
    assert data["exchange_rates"] == [
        {"source_currency": "EUR", "target_currency": "RSD", "rate": "100", "rate_date": "2026-11-06"}
    ]

    stock_refresh = client.get("/v1/staff/stock", headers=auth)
    item = next(row for row in stock_refresh.json()["items"] if row["stock_id"] == str(stock.id))
    assert item["price"] == {"amount_minor": 12_000, "currency": "RSD"}


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
