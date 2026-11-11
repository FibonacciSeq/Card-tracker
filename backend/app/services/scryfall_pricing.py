"""Apply shop pricing rules to current Scryfall market prices."""

from __future__ import annotations

import time
from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx
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

# The Scryfall collection endpoint accepts at most 75 identifiers per call
# and asks for a pause between requests so bursts stay under 10 calls/second.
SCRYFALL_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
SCRYFALL_USER_AGENT = "CardTracker/1.0 (manual price refresh)"
SCRYFALL_COLLECTION_BATCH_SIZE = 75
SCRYFALL_COLLECTION_PAUSE_SECONDS = 0.1
SCRYFALL_TIMEOUT_SECONDS = 15.0


class ScryfallUnavailableError(Exception):
    """Scryfall could not be reached or returned unusable market data."""


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


def _fetch_scryfall_prices(http_client: httpx.Client, provider_ids: list[str]) -> dict[str, Any]:
    """Fetch current prices from the Scryfall collection endpoint, by card id."""
    try:
        response = http_client.post(
            SCRYFALL_COLLECTION_URL,
            json={"identifiers": [{"id": provider_id} for provider_id in provider_ids]},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ScryfallUnavailableError("Scryfall market prices are unavailable right now. Try again later.") from exc
    if not isinstance(payload, dict) or payload.get("object") != "list":
        raise ScryfallUnavailableError("Scryfall market prices are unavailable right now. Try again later.")
    prices: dict[str, Any] = {}
    for obj in payload.get("data", []):
        if not isinstance(obj, dict) or obj.get("id") is None:
            continue
        prices[str(obj["id"])] = obj.get("prices")
    return prices


def refresh_stock_market_prices(
    db: Session,
    tenant: models.Tenant,
    client: httpx.Client | None = None,
) -> tuple[int, int]:
    """Fetch current Scryfall market prices for the cards this shop stocks.

    Updates the stored catalog prices so a following reprice uses fresh data.
    Returns ``(cards_refreshed, cards_unavailable)``; cards that are not in the
    Scryfall catalog or no longer report prices count as unavailable.
    """
    cards = db.scalars(
        select(models.Card)
        .join(models.Stock, models.Stock.card_id == models.Card.id)
        .where(
            models.Stock.tenant_id == tenant.id,
            models.Stock.archived_at.is_(None),
        )
        .distinct()
    ).all()
    refreshable = [row for row in cards if row.provider == "scryfall" and row.provider_card_id]
    unavailable = len(cards) - len(refreshable)
    refreshed = 0
    if refreshable:
        owns_client = client is None
        http_client = client or httpx.Client(
            timeout=SCRYFALL_TIMEOUT_SECONDS,
            headers={"User-Agent": SCRYFALL_USER_AGENT},
        )
        try:
            for start in range(0, len(refreshable), SCRYFALL_COLLECTION_BATCH_SIZE):
                batch = refreshable[start : start + SCRYFALL_COLLECTION_BATCH_SIZE]
                if start:
                    time.sleep(SCRYFALL_COLLECTION_PAUSE_SECONDS)
                fresh = _fetch_scryfall_prices(http_client, [row.provider_card_id for row in batch])
                for row in batch:
                    prices = fresh.get(row.provider_card_id)
                    if not isinstance(prices, dict):
                        unavailable += 1
                        continue
                    row.scryfall_prices = prices
                    refreshed += 1
        finally:
            if owns_client:
                http_client.close()
    return refreshed, unavailable


def price_import_rows(
    db: Session,
    tenant: models.Tenant,
    rows: list[stock_csv.ImportRow],
    pricing: dict[str, int],
) -> tuple[list[stock_csv.ImportRow], list[stock_csv.RowError]]:
    """Use Scryfall market prices when available, otherwise retain CSV prices."""
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
            priced_rows.append(row)
            continue
        priced_rows.append(replace(row, price_minor=price, currency=tenant.currency.upper(), uses_pricing_rules=False))
    return priced_rows, errors
