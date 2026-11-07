"""Refresh Scryfall market data and shop stock prices every night."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

import ijson
import requests
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app import models
from app.cli.import_scryfall import _card_fields
from app.db import SessionLocal, set_tenant_context
from app.services import exchange_rates, scryfall_pricing

logger = logging.getLogger(__name__)
SCRYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
USER_AGENT = "CardTracker/1.0 (Scryfall daily price refresh)"
BATCH_SIZE = 500
REFRESH_HOUR_UTC = 2
REQUEST_TIMEOUT = (15, 300)


def seconds_until_next_refresh(now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    target = current.replace(hour=REFRESH_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return (target - current).total_seconds()


def default_cards_download_url(client: requests.Session) -> str:
    response = client.get(
        SCRYFALL_BULK_DATA_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Scryfall bulk-data response was not a JSON object.")
    datasets = payload.get("data")
    if not isinstance(datasets, list):
        raise RuntimeError("Scryfall bulk-data response did not contain a dataset list.")
    for dataset in datasets:
        if isinstance(dataset, dict) and dataset.get("type") == "default_cards":
            download_uri = dataset.get("download_uri")
            if isinstance(download_uri, str) and download_uri.startswith("https://"):
                return download_uri
    raise RuntimeError("Scryfall did not publish a default-cards bulk dataset.")


def update_catalog_prices(db, source: BinaryIO) -> int:
    card_ids = dict(
        db.execute(select(models.Card.provider_card_id, models.Card.id).where(models.Card.provider == "scryfall")).all()
    )
    new_provider_ids: set[str] = set()
    updates: list[dict[str, Any]] = []
    creates: list[models.Card] = []
    processed = 0

    for obj in ijson.items(source, "item"):
        if not isinstance(obj, dict) or obj.get("object") != "card" or not obj.get("id"):
            continue
        provider_id = str(obj["id"])
        if provider_id in new_provider_ids:
            continue
        prices = obj.get("prices")
        normalized_prices = prices if isinstance(prices, dict) else {}
        card_id = card_ids.get(provider_id)
        if card_id is None:
            creates.append(models.Card(**_card_fields(obj, store_raw=False)))
            new_provider_ids.add(provider_id)
        else:
            updates.append({"id": card_id, "scryfall_prices": normalized_prices})

        processed += 1
        if processed % BATCH_SIZE == 0:
            if updates:
                db.bulk_update_mappings(models.Card, updates)
                updates.clear()
            if creates:
                db.add_all(creates)
                creates.clear()
            db.commit()
            logger.info("Refreshed Scryfall prices for %s catalog cards", processed)

    if updates:
        db.bulk_update_mappings(models.Card, updates)
    if creates:
        db.add_all(creates)
    db.commit()
    if processed == 0:
        raise RuntimeError("Scryfall default-cards data contained no card records.")
    return processed


def reprice_configured_shops() -> tuple[int, int]:
    updated = skipped = 0
    with SessionLocal() as db:
        tenant_ids = db.scalars(select(models.Tenant.id)).all()
        for tenant_id in tenant_ids:
            try:
                db.rollback()
                set_tenant_context(db, tenant_id)
                tenant = db.scalar(
                    select(models.Tenant)
                    .options(selectinload(models.Tenant.settings))
                    .where(models.Tenant.id == tenant_id)
                )
                if tenant is None:
                    continue
                pricing = scryfall_pricing.pricing_settings(tenant.settings)
                if pricing is None:
                    continue
                changed, missing_prices = scryfall_pricing.reprice_tenant_stock(db, tenant, pricing)
                db.commit()
                updated += changed
                skipped += missing_prices
                logger.info(
                    "Repriced %s stock row(s) for shop %s; %s had no Scryfall finish price",
                    changed,
                    tenant.slug,
                    missing_prices,
                )
            except (exchange_rates.ExchangeRateError, ValueError):
                db.rollback()
                logger.exception("Could not reprice Scryfall stock for tenant %s", tenant_id)
    return updated, skipped


def _run_once(http: requests.Session) -> tuple[int, int, int]:
    download_uri = default_cards_download_url(http)
    with http.get(
        download_uri,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    ) as response:
        response.raise_for_status()
        with SessionLocal() as db:
            processed = update_catalog_prices(db, response.raw)
    updated, skipped = reprice_configured_shops()
    logger.info(
        "Scryfall refresh complete: %s cards read, %s stock prices updated, %s stock rows skipped",
        processed,
        updated,
        skipped,
    )
    return processed, updated, skipped


def run_once(client: requests.Session | None = None) -> tuple[int, int, int]:
    if client is not None:
        return _run_once(client)
    with requests.Session() as http:
        return _run_once(http)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Scryfall pricing worker started; daily refresh is scheduled for %02d:00 UTC", REFRESH_HOUR_UTC)
    while True:
        try:
            run_once()
        except (
            ijson.JSONError,
            requests.RequestException,
            RuntimeError,
            SQLAlchemyError,
            exchange_rates.ExchangeRateError,
            ValueError,
        ):
            logger.exception("Scryfall pricing refresh failed; prices were not fully refreshed")
        time.sleep(seconds_until_next_refresh())


if __name__ == "__main__":  # pragma: no cover
    main()
