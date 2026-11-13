"""Owner-triggered Scryfall market price refresh."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app import models
from app.config import settings as config_settings
from app.security import create_access_token
from app.services import exchange_rates, scryfall_pricing

RULES = {
    "enabled": True,
    "minimum_price_minor": 1_000,
    "markup_percent": 10,
    "rounding_increment_minor": 500,
}


class TrackedClient(httpx.Client):
    """httpx client that records close() so ownership can be asserted."""

    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def _collection_client(
    *,
    status_code: int = 200,
    payload: dict | None = None,
    prices: dict | None = None,
    raw: bytes | None = None,
):
    """Mock the Scryfall collection endpoint.

    Returns ``(client, calls)`` where ``calls`` records the provider ids sent
    with each request. Cards listed in ``prices`` report that price dict; cards
    missing from ``prices`` report no prices at all.
    """
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        identifiers = json.loads(request.content)["identifiers"]
        calls.append([item["id"] for item in identifiers])
        if raw is not None:
            return httpx.Response(status_code, content=raw, headers={"Content-Type": "application/json"})
        if payload is not None:
            return httpx.Response(status_code, json=payload)
        data = [
            {"id": item["id"], "prices": prices.get(item["id"]) if prices else {"usd": "1.23"}} for item in identifiers
        ]
        return httpx.Response(status_code, json={"object": "list", "data": data})

    return TrackedClient(transport=httpx.MockTransport(handler)), calls


def _extra_card(db, tenant, provider_card_id, *, finish="nonfoil"):
    card = models.Card(
        id=uuid.uuid4(),
        provider_card_id=provider_card_id,
        name=f"Card {provider_card_id}",
        set_code="X",
        set_name="Set X",
        collector_number="1",
        rarity="common",
        type_line="Creature",
    )
    db.add(card)
    db.add(
        models.Stock(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            card_id=card.id,
            finish=finish,
            condition="NM",
            language="en",
            quantity=1,
            price_minor=100,
            currency="RSD",
            is_online=True,
        )
    )
    db.commit()
    db.refresh(card)
    return card


def test_refresh_updates_catalog_prices_for_stocked_cards(db, tenant, card, stock):
    client, calls = _collection_client(prices={"scryfall-lightning-bolt": {"usd": "3.50"}})

    assert scryfall_pricing.refresh_stock_market_prices(db, tenant, client) == (1, 0)
    assert card.scryfall_prices == {"usd": "3.50"}
    assert calls == [["scryfall-lightning-bolt"]]
    # An injected client stays owned by the caller.
    assert client.closed is False


def test_refresh_counts_cards_scryfall_cannot_price(db, tenant, card, stock):
    gone = _extra_card(db, tenant, "scryfall-gone")
    unlinked = _extra_card(db, tenant, "")
    client, calls = _collection_client(prices={"scryfall-lightning-bolt": {"usd": "5.00"}, "scryfall-gone": None})

    assert scryfall_pricing.refresh_stock_market_prices(db, tenant, client) == (1, 2)
    assert card.scryfall_prices == {"usd": "5.00"}
    assert gone.scryfall_prices is None
    assert unlinked.provider_card_id == ""
    # Cards without a Scryfall id are never requested.
    assert len(calls) == 1
    assert set(calls[0]) == {"scryfall-lightning-bolt", "scryfall-gone"}


def test_refresh_ignores_malformed_collection_entries(db, tenant, card, stock):
    client, _calls = _collection_client(payload={"object": "list", "data": ["junk", {"no_id": True}]})

    assert scryfall_pricing.refresh_stock_market_prices(db, tenant, client) == (0, 1)
    assert card.scryfall_prices is None


@pytest.mark.parametrize(
    "client_kwargs",
    [
        {"status_code": 503},
        {"raw": b"<html>service unavailable</html>"},
        {"payload": {"object": "error"}},
    ],
)
def test_refresh_maps_scryfall_failures(db, tenant, card, stock, client_kwargs):
    client, _calls = _collection_client(**client_kwargs)

    with pytest.raises(scryfall_pricing.ScryfallUnavailableError, match="unavailable right now"):
        scryfall_pricing.refresh_stock_market_prices(db, tenant, client)


def test_refresh_batches_requests_with_a_pause(db, tenant, monkeypatch):
    for index in range(3):
        _extra_card(db, tenant, f"scryfall-{index}")
    monkeypatch.setattr(scryfall_pricing, "SCRYFALL_COLLECTION_BATCH_SIZE", 2)
    pauses: list[float] = []
    monkeypatch.setattr(scryfall_pricing.time, "sleep", pauses.append)
    client, calls = _collection_client()

    assert scryfall_pricing.refresh_stock_market_prices(db, tenant, client) == (3, 0)
    assert [len(batch) for batch in calls] == [2, 1]
    assert {item for batch in calls for item in batch} == {"scryfall-0", "scryfall-1", "scryfall-2"}
    assert pauses == [scryfall_pricing.SCRYFALL_COLLECTION_PAUSE_SECONDS]


def test_refresh_without_scryfall_cards_avoids_the_network(db, tenant, card, stock):
    card.provider_card_id = ""
    db.commit()
    client, calls = _collection_client()

    assert scryfall_pricing.refresh_stock_market_prices(db, tenant, client) == (0, 1)
    assert calls == []


def test_refresh_owns_a_default_http_client(db, tenant, card, stock, monkeypatch):
    instances: list[FakeClient] = []

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {
                "timeout": scryfall_pricing.SCRYFALL_TIMEOUT_SECONDS,
                "headers": {"User-Agent": scryfall_pricing.SCRYFALL_USER_AGENT},
            }
            self.closed = False
            instances.append(self)

        def post(self, url, **kwargs):
            assert url == scryfall_pricing.SCRYFALL_COLLECTION_URL
            assert kwargs == {"json": {"identifiers": [{"id": card.provider_card_id}]}}
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": card.provider_card_id}]},
                request=httpx.Request("POST", url),
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(scryfall_pricing.httpx, "Client", FakeClient)

    # The card is not in the response data, so it counts as unavailable.
    assert scryfall_pricing.refresh_stock_market_prices(db, tenant) == (0, 1)
    assert [instance.closed for instance in instances] == [True]


def _make_staff_token(db, tenant):
    row = models.User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"staff-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="not-a-real-hash",
        role="staff",
        display_name="Staff",
    )
    db.add(row)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(row.id, tenant.id, row.role)}"}


def test_refresh_requires_the_owner_role(client, tenant, owner, stock, auth, db):
    response = client.post(
        "/v1/staff/settings/scryfall-refresh",
        headers=_make_staff_token(db, tenant),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Owner role required"


def test_refresh_requires_enabled_pricing(client, tenant, owner, auth):
    response = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert response.status_code == 422
    assert "minimum price and markup" in response.json()["detail"]


def test_refresh_fetches_prices_and_reprices_stock(client, tenant, owner, stock, card, auth, db, monkeypatch):
    tenant.settings.scryfall_pricing = dict(RULES)
    db.commit()

    def fake_client(**_kwargs):
        client, _calls = _collection_client(prices={"scryfall-lightning-bolt": {"usd": "2.00"}})
        return client

    monkeypatch.setattr(scryfall_pricing.httpx, "Client", fake_client)
    monkeypatch.setattr(
        "app.services.scryfall_pricing.exchange_rates.get_latest_rate",
        lambda source, target: exchange_rates.ExchangeRate(source, target, Decimal("100"), date(2026, 11, 10)),
    )

    response = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "cards_refreshed": 1,
        "cards_unavailable": 0,
        "repriced_stock": 1,
        "stock_without_scryfall_prices": 0,
    }

    db.expire_all()
    assert db.get(models.Stock, stock.id).price_minor == 22_500
    events = db.scalars(select(models.AuditEvent).where(models.AuditEvent.tenant_id == tenant.id)).all()
    assert [event.action for event in events] == ["stock.reprice"]
    assert events[0].data["cards_refreshed"] == 1


def test_refresh_succeeds_without_network_when_no_card_is_in_scryfall(client, tenant, owner, stock, card, auth, db):
    card.provider_card_id = ""
    tenant.settings.scryfall_pricing = dict(RULES)
    db.commit()

    response = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "cards_refreshed": 0,
        "cards_unavailable": 1,
        "repriced_stock": 0,
        "stock_without_scryfall_prices": 1,
    }


def test_refresh_surfaces_scryfall_outages(client, tenant, owner, stock, card, auth, db, monkeypatch):
    tenant.settings.scryfall_pricing = dict(RULES)
    db.commit()

    def fake_client(**_kwargs):
        client, _calls = _collection_client(status_code=503)
        return client

    monkeypatch.setattr(scryfall_pricing.httpx, "Client", fake_client)

    response = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert response.status_code == 503
    assert response.json()["detail"] == ("Scryfall market prices are unavailable right now. Try again later.")


def test_refresh_surfaces_exchange_rate_failures(client, tenant, owner, stock, card, auth, db, monkeypatch):
    tenant.settings.scryfall_pricing = dict(RULES)
    tenant.currency = "RSD"
    db.commit()

    def fake_client(**_kwargs):
        client, _calls = _collection_client(prices={"scryfall-lightning-bolt": {"usd": "2.00"}})
        return client

    def raise_error(source, target):
        raise exchange_rates.ExchangeRateError("no reference rate today")

    monkeypatch.setattr(scryfall_pricing.httpx, "Client", fake_client)
    monkeypatch.setattr(
        "app.services.scryfall_pricing.exchange_rates.get_latest_rate",
        raise_error,
    )

    response = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert response.status_code == 503
    assert response.json()["detail"] == "no reference rate today"


def test_refresh_surfaces_overflow_as_unprocessable(client, tenant, owner, stock, card, auth, db, monkeypatch):
    tenant.currency = "USD"
    tenant.settings.scryfall_pricing = {
        "enabled": True,
        "minimum_price_minor": 0,
        "markup_percent": 10_000,
        "rounding_increment_minor": 2_147_483_600,
    }
    db.commit()

    def fake_client(**_kwargs):
        client, _calls = _collection_client(prices={"scryfall-lightning-bolt": {"usd": "3000000"}})
        return client

    monkeypatch.setattr(scryfall_pricing.httpx, "Client", fake_client)

    response = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert response.status_code == 422
    assert response.json()["detail"] == "Calculated sale price exceeds the supported range."


def test_refresh_is_rate_limited(client, tenant, owner, stock, card, auth, db, monkeypatch):
    card.provider_card_id = ""
    tenant.settings.scryfall_pricing = dict(RULES)
    db.commit()
    monkeypatch.setattr(config_settings, "scryfall_refresh_ip_limit", 2)

    for _ in range(2):
        first = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
        assert first.status_code == 200

    throttled = client.post("/v1/staff/settings/scryfall-refresh", headers=auth)
    assert throttled.status_code == 429
    assert throttled.headers["Retry-After"].isdigit()
