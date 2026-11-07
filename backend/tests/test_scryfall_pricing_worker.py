from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import cast

import ijson
import pytest
import requests
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app import models
from app.services.exchange_rates import ExchangeRateError
from app.workers import scryfall_pricing as worker


def test_update_catalog_prices_updates_existing_and_adds_new_card(db, card, monkeypatch):
    monkeypatch.setattr(worker, "BATCH_SIZE", 1)
    source = BytesIO(
        json.dumps(
            [
                None,
                {"object": "set", "id": "ignored-set"},
                {"object": "card"},
                {
                    "object": "card",
                    "id": card.provider_card_id,
                    "prices": {"usd": "1.25", "usd_foil": None},
                },
                {
                    "object": "card",
                    "id": "new-scryfall-card",
                    "name": "New Card",
                    "set": "new",
                    "set_name": "New Set",
                    "collector_number": "1",
                    "prices": {"usd": "2.50"},
                },
                {
                    "object": "card",
                    "id": "new-scryfall-card",
                    "name": "Duplicate new card",
                    "set": "new",
                    "set_name": "New Set",
                    "collector_number": "1",
                    "prices": {"usd": "9.99"},
                },
            ]
        ).encode()
    )

    assert worker.update_catalog_prices(db, source) == 2
    db.expire_all()
    assert db.get(models.Card, card.id).scryfall_prices == {"usd": "1.25", "usd_foil": None}
    new_card = db.query(models.Card).filter_by(provider_card_id="new-scryfall-card").one()
    assert new_card.scryfall_prices == {"usd": "2.50"}


def test_update_catalog_prices_flushes_pending_creates_at_end(db, monkeypatch):
    source = BytesIO(
        json.dumps(
            [
                {
                    "object": "card",
                    "id": "final-batch-card",
                    "name": "Final Batch Card",
                    "set": "new",
                    "set_name": "New Set",
                    "collector_number": "2",
                    "prices": {"usd": "2.50"},
                }
            ]
        ).encode()
    )
    monkeypatch.setattr(worker, "BATCH_SIZE", 10)

    assert worker.update_catalog_prices(db, source) == 1
    assert db.query(models.Card).filter_by(provider_card_id="final-batch-card").one().scryfall_prices == {"usd": "2.50"}


def test_update_catalog_prices_rejects_empty_bulk_data(db):
    with pytest.raises(RuntimeError, match="no card records"):
        worker.update_catalog_prices(db, BytesIO(b"[]"))


def test_seconds_until_next_refresh_uses_0200_utc():
    before = datetime(2026, 11, 7, 1, 59, tzinfo=UTC)
    at_refresh = datetime(2026, 11, 7, 2, 0, tzinfo=UTC)
    assert worker.seconds_until_next_refresh(before) == 60
    assert worker.seconds_until_next_refresh(at_refresh) == 24 * 60 * 60


class _Response:
    def __init__(self, payload=None, raw=None):
        self.payload = payload
        self.raw = raw

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, *_args, **_kwargs):
        return self.responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_default_cards_download_url_selects_default_dataset():
    response = _Response(
        {
            "data": [
                "bad-entry",
                {"type": "oracle_cards", "download_uri": "https://example.test/oracle"},
                {"type": "default_cards", "download_uri": "https://example.test/default"},
            ]
        }
    )
    client = cast(requests.Session, _Client([response]))
    assert worker.default_cards_download_url(client) == "https://example.test/default"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"data": None},
        {"data": [{"type": "default_cards", "download_uri": "http://example.test/cards"}]},
    ],
)
def test_default_cards_download_url_rejects_bad_metadata(payload):
    client = cast(requests.Session, _Client([_Response(payload)]))
    with pytest.raises(RuntimeError):
        worker.default_cards_download_url(client)


def test_run_once_streams_latest_bulk_and_reprices_shops(db, card, monkeypatch):
    source = BytesIO(json.dumps([{"object": "card", "id": card.provider_card_id, "prices": {"usd": "3.00"}}]).encode())
    client = cast(
        requests.Session,
        _Client(
            [
                _Response({"data": [{"type": "default_cards", "download_uri": "https://example.test/cards"}]}),
                _Response(raw=source),
            ]
        ),
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False),
    )
    monkeypatch.setattr(worker, "reprice_configured_shops", lambda: (2, 1))

    assert worker.run_once(client) == (1, 2, 1)


def test_run_once_owns_and_closes_its_http_session(monkeypatch):
    client = _Client([])
    monkeypatch.setattr(worker.requests, "Session", lambda: client)
    monkeypatch.setattr(worker, "_run_once", lambda _http: (1, 0, 0))
    assert worker.run_once() == (1, 0, 0)


def test_reprice_configured_shops_updates_enabled_shop_stock(db, tenant, card, stock, monkeypatch):
    tenant.currency = "USD"
    tenant.settings.scryfall_pricing = {
        "enabled": True,
        "minimum_price_minor": 1_000,
        "markup_percent": 10,
        "rounding_increment_minor": 500,
    }
    card.scryfall_prices = {"usd": "10.00"}
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False),
    )

    assert worker.reprice_configured_shops() == (1, 0)
    db.expire_all()
    assert db.get(models.Stock, stock.id).price_minor == 1_500


def test_reprice_configured_shops_logs_rate_failures_and_continues(db, tenant, card, stock, monkeypatch):
    tenant.currency = "RSD"
    tenant.settings.scryfall_pricing = {
        "enabled": True,
        "minimum_price_minor": 1_000,
        "markup_percent": 10,
        "rounding_increment_minor": 500,
    }
    card.scryfall_prices = {"usd": "10.00"}
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False),
    )
    monkeypatch.setattr(
        worker.exchange_rates,
        "get_latest_rate",
        lambda *_args: (_ for _ in ()).throw(ExchangeRateError("rate unavailable")),
    )

    assert worker.reprice_configured_shops() == (0, 0)
    db.expire_all()
    assert db.get(models.Stock, stock.id).price_minor == 125_000


def test_reprice_configured_shops_skips_missing_tenants_and_unconfigured_settings(monkeypatch):
    class Result:
        def all(self):
            return ["deleted-tenant", "unconfigured-tenant"]

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _query):
            return Result()

        def rollback(self):
            return None

        def scalar(self, _query):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return None
            return models.Tenant(
                id="unconfigured-tenant",
                slug="unconfigured",
                name="Unconfigured",
                currency="USD",
            )

    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(worker, "set_tenant_context", lambda *_args: None)
    assert worker.reprice_configured_shops() == (0, 0)


@pytest.mark.parametrize(
    "failure",
    [
        ijson.JSONError("bad JSON"),
        requests.RequestException("offline"),
        RuntimeError("bad metadata"),
        SQLAlchemyError("database unavailable"),
        ExchangeRateError("rate unavailable"),
        ValueError("price overflow"),
    ],
)
def test_worker_main_logs_refresh_errors_and_retries_next_day(monkeypatch, failure):
    monkeypatch.setattr(worker, "run_once", lambda: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        worker.main()
