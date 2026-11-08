"""Apply shop pricing rules to current Scryfall market prices."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services import exchange_rates, stock_csv

PRICE_FIELDS = {
    ("nonfoil", "USD"): "usd",
    ("nonfoil", "EUR"): "eur",
    ("foil", "USD"): "usd_foil",
    ("foil", "EUR"): "eur_foil",
    ("etched", "USD"): "usd_etched",
}


def pricing_settings(settings_row: models.TenantSettings | None) -> dict[str, int] | None:
    config = settings_row.scryfall_pricing if settings_row else None
    fields = ("minimum_price_minor", "markup_percent")
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return None
    if not all(type(config.get(field)) is int for field in fields):
        return None
    if not 0 <= config["minimum_price_minor"] <= 2_147_483_647:
        return None
    if not 0 <= config["markup_percent"] <= 10_000:
        return None
    rounding_increment_minor = config.get("rounding_increment_minor", 500)
    if type(rounding_increment_minor) is not int or not 100 <= rounding_increment_minor <= 2_147_483_600:
        return None
    if rounding_increment_minor % 100 != 0:
        return None
    return {
        **{field: config[field] for field in fields},
        "rounding_increment_minor": rounding_increment_minor,
    }


def _market_price(prices: Any, finish: str, currency: str) -> tuple[Decimal, str] | None:
    if not isinstance(prices, dict):
        return None
    target_currency = currency.upper()
    source_currency = target_currency if target_currency in ("USD", "EUR") else "USD"
    field = PRICE_FIELDS.get((finish, source_currency))
    if field is None and finish == "etched" and source_currency == "EUR":
        source_currency = "USD"
        field = PRICE_FIELDS[(finish, source_currency)]
    if field is None:
        return None
    raw_price = prices.get(field)
    if raw_price is None:
        return None
    try:
        amount = Decimal(str(raw_price))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount, source_currency


def _exchange_rate(source_currency: str, target_currency: str) -> Decimal:
    if source_currency == target_currency:
        return Decimal("1")
    return exchange_rates.get_latest_rate(source_currency, target_currency).rate


def _rates_for_markets(
    target_currency: str,
    markets: list[tuple[Decimal, str] | None],
) -> dict[str, Decimal]:
    sources = {market[1] for market in markets if market is not None}
    return {source: _exchange_rate(source, target_currency.upper()) for source in sources}


def calculate_sale_price(
    market_price: Decimal,
    source_currency: str,
    target_currency: str,
    pricing: dict[str, int],
    exchange_rate: Decimal | None = None,
) -> int:
    rate = exchange_rate if exchange_rate is not None else _exchange_rate(source_currency, target_currency)
    market_minor = int((market_price * rate * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    minimum_price = pricing["minimum_price_minor"]
    if market_minor < minimum_price:
        return minimum_price

    marked_up_minor = int(
        (Decimal(market_minor) * Decimal(100 + pricing["markup_percent"]) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
    )
    rounding_increment_minor = pricing["rounding_increment_minor"]
    rounded_minor = (marked_up_minor // rounding_increment_minor + 1) * rounding_increment_minor
    if rounded_minor > 2_147_483_647:
        raise ValueError("Calculated sale price exceeds the supported range.")
    return rounded_minor


def price_for_card(
    card: models.Card,
    finish: str,
    target_currency: str,
    pricing: dict[str, int],
    rates: dict[str, Decimal] | None = None,
) -> int | None:
    market = _market_price(card.scryfall_prices, finish, target_currency)
    if market is None:
        return None
    market_price, source_currency = market
    rate = (rates or {}).get(source_currency)
    return calculate_sale_price(
        market_price,
        source_currency,
        target_currency.upper(),
        pricing,
        rate,
    )


def reprice_tenant_stock(
    db: Session,
    tenant: models.Tenant,
    pricing: dict[str, int],
) -> tuple[int, int]:
    """Reprice from catalog market data, returning changed and skipped rows."""
    currency = tenant.currency.upper()
    rows = db.execute(
        select(models.Stock, models.Card)
        .join(models.Card, models.Card.id == models.Stock.card_id)
        .where(
            models.Stock.tenant_id == tenant.id,
            models.Stock.archived_at.is_(None),
        )
    ).all()
    markets = [_market_price(card.scryfall_prices, stock.finish, currency) for stock, card in rows]
    rates = _rates_for_markets(currency, markets)
    updated = skipped = 0
    for stock, card in rows:
        new_price = price_for_card(card, stock.finish, currency, pricing, rates)
        if new_price is None:
            skipped += 1
        elif new_price != stock.price_minor:
            stock.price_minor = new_price
            stock.updated_at = models.utcnow()
            updated += 1
    return updated, skipped


def price_import_rows(
    db: Session,
    tenant: models.Tenant,
    rows: list[stock_csv.ImportRow],
    pricing: dict[str, int],
) -> tuple[list[stock_csv.ImportRow], list[stock_csv.RowError]]:
    """Use Scryfall market prices for imports; skip catalog rows without prices."""
    set_codes = {row.set_code.upper() for row in rows}
    cards_by_key: dict[tuple[str, str], models.Card] = {}
    if set_codes:
        cards = db.scalars(select(models.Card).where(func.upper(models.Card.set_code).in_(set_codes))).all()
        for catalog_item in cards:
            cards_by_key[(catalog_item.set_code.upper(), catalog_item.collector_number.upper())] = catalog_item

    markets = [
        _market_price(matching_card.scryfall_prices, row.finish, tenant.currency)
        if (matching_card := cards_by_key.get((row.set_code.upper(), row.collector_number.upper()))) is not None
        else None
        for row in rows
    ]
    rates = _rates_for_markets(tenant.currency, markets)
    priced_rows: list[stock_csv.ImportRow] = []
    errors: list[stock_csv.RowError] = []
    for row in rows:
        catalog_card = cards_by_key.get((row.set_code.upper(), row.collector_number.upper()))
        if catalog_card is None:
            priced_rows.append(row)
            continue
        price = price_for_card(catalog_card, row.finish, tenant.currency, pricing, rates)
        if price is None:
            errors.append(
                stock_csv.RowError(
                    row.line,
                    "No Scryfall market price for this card and finish; row skipped.",
                    "collector_number",
                )
            )
            continue
        priced_rows.append(replace(row, price_minor=price, currency=tenant.currency.upper(), uses_pricing_rules=False))
    return priced_rows, errors
