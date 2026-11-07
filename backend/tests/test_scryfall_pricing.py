from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import models
from app.services import exchange_rates, scryfall_pricing, stock_csv

RULES = {"minimum_price_minor": 1_000, "markup_percent": 10, "rounding_increment_minor": 500}


def test_pricing_settings_requires_valid_enabled_values():
    assert scryfall_pricing.pricing_settings(None) is None
    assert scryfall_pricing.pricing_settings(models.TenantSettings(scryfall_pricing=[])) is None
    assert (
        scryfall_pricing.pricing_settings(
            models.TenantSettings(scryfall_pricing={"enabled": False, "minimum_price_minor": 0, "markup_percent": 0})
        )
        is None
    )
    assert (
        scryfall_pricing.pricing_settings(
            models.TenantSettings(scryfall_pricing={"enabled": True, "minimum_price_minor": True, "markup_percent": 0})
        )
        is None
    )
    assert (
        scryfall_pricing.pricing_settings(
            models.TenantSettings(
                scryfall_pricing={"enabled": True, "minimum_price_minor": 2_147_483_648, "markup_percent": 0}
            )
        )
        is None
    )
    assert (
        scryfall_pricing.pricing_settings(
            models.TenantSettings(
                scryfall_pricing={"enabled": True, "minimum_price_minor": 0, "markup_percent": 10_001}
            )
        )
        is None
    )
    assert scryfall_pricing.pricing_settings(
        models.TenantSettings(scryfall_pricing={"enabled": True, "minimum_price_minor": 0, "markup_percent": 0})
    ) == {"minimum_price_minor": 0, "markup_percent": 0, "rounding_increment_minor": 500}
    for invalid_increment in (True, 0, 99, 150, 2_147_483_700):
        assert (
            scryfall_pricing.pricing_settings(
                models.TenantSettings(
                    scryfall_pricing={
                        "enabled": True,
                        "minimum_price_minor": 0,
                        "markup_percent": 0,
                        "rounding_increment_minor": invalid_increment,
                    }
                )
            )
            is None
        )


def test_market_price_validation_and_finish_currency_selection():
    assert scryfall_pricing._market_price(None, "nonfoil", "USD") is None
    assert scryfall_pricing._market_price({}, "nonfoil", "USD") is None
    assert scryfall_pricing._market_price({"usd": None}, "nonfoil", "USD") is None
    assert scryfall_pricing._market_price({"usd": "not-money"}, "nonfoil", "USD") is None
    assert scryfall_pricing._market_price({"usd": "-1"}, "nonfoil", "USD") is None
    assert scryfall_pricing._market_price({"usd": "NaN"}, "nonfoil", "USD") is None
    assert scryfall_pricing._market_price({"other": "1"}, "unknown", "USD") is None
    assert scryfall_pricing._market_price({"usd_etched": "3.25"}, "etched", "EUR") == (
        Decimal("3.25"),
        "USD",
    )
    assert scryfall_pricing._market_price({"eur_foil": "2.50"}, "foil", "EUR") == (
        Decimal("2.50"),
        "EUR",
    )
    assert scryfall_pricing._market_price({"usd_foil": "1.25"}, "foil", "RSD") == (
        Decimal("1.25"),
        "USD",
    )


def test_rate_helpers_use_same_currency_or_fetch_market_currency(monkeypatch):
    calls = []

    def get_rate(source, target):
        calls.append((source, target))
        return exchange_rates.ExchangeRate(source, target, Decimal("117"), date.today())

    monkeypatch.setattr(scryfall_pricing.exchange_rates, "get_latest_rate", get_rate)
    assert scryfall_pricing._exchange_rate("EUR", "EUR") == Decimal("1")
    assert scryfall_pricing._rates_for_markets("EUR", []) == {}
    rates = scryfall_pricing._rates_for_markets(
        "RSD",
        [(Decimal("1"), "USD"), None, (Decimal("2"), "EUR")],
    )
    assert rates == {"USD": Decimal("117"), "EUR": Decimal("117")}
    assert set(calls) == {("USD", "RSD"), ("EUR", "RSD")}


def test_sale_price_checks_supported_integer_range():
    with pytest.raises(ValueError, match="supported range"):
        scryfall_pricing.calculate_sale_price(
            Decimal("21474836.47"),
            "USD",
            "USD",
            {"minimum_price_minor": 0, "markup_percent": 100, "rounding_increment_minor": 500},
        )


def test_sale_price_rounds_up_by_configured_whole_currency_increment():
    five_unit_increment = {
        "minimum_price_minor": 0,
        "markup_percent": 0,
        "rounding_increment_minor": 500,
    }
    assert scryfall_pricing.calculate_sale_price(Decimal("121"), "USD", "USD", five_unit_increment) == 12_500
    assert scryfall_pricing.calculate_sale_price(Decimal("125"), "USD", "USD", five_unit_increment) == 13_000

    ten_unit_increment = {**five_unit_increment, "rounding_increment_minor": 1_000}
    assert scryfall_pricing.calculate_sale_price(Decimal("121"), "USD", "USD", ten_unit_increment) == 13_000


def test_price_for_card_and_stock_repricing_skip_missing_and_leave_unchanged(db, tenant, card, stock):
    card.scryfall_prices = {"usd": "10.00"}
    tenant.currency = "USD"
    missing_price_stock = models.Stock(
        tenant_id=tenant.id,
        card_id=card.id,
        finish="foil",
        condition="NM",
        language="en",
        quantity=1,
        price_minor=500,
        currency="USD",
    )
    db.add(missing_price_stock)
    db.commit()

    assert scryfall_pricing.price_for_card(card, "foil", "USD", RULES) is None
    assert scryfall_pricing.price_for_card(card, "nonfoil", "USD", RULES) == 1_500
    assert scryfall_pricing.reprice_tenant_stock(db, tenant, RULES) == (1, 1)
    assert stock.price_minor == 1_500
    assert missing_price_stock.price_minor == 500
    assert scryfall_pricing.reprice_tenant_stock(db, tenant, RULES) == (0, 1)


def test_stock_repricing_and_import_skip_do_not_fetch_rates_without_catalog_price(db, tenant):
    tenant.currency = "RSD"
    assert scryfall_pricing.reprice_tenant_stock(db, tenant, RULES) == (0, 0)
    assert scryfall_pricing.price_import_rows(db, tenant, [], RULES) == ([], [])
    row, errors = stock_csv.parse_csv(
        "set_code,collector_number,quantity,price\nMISSING,1,1,1.00\n",
        tenant.currency,
    )
    assert errors == []
    imported, price_errors = scryfall_pricing.price_import_rows(db, tenant, row, RULES)
    assert len(imported) == 1
    assert price_errors == []
