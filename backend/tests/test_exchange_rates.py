from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app.services import exchange_rates
from app.services.exchange_rates import ExchangeRateError, get_latest_rate


def test_latest_reference_rate_parses_daily_quote():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "result": "success",
                    "base_code": "EUR",
                    "time_last_update_unix": int(datetime(2026, 11, 6, tzinfo=UTC).timestamp()),
                    "rates": {"RSD": 117.2},
                },
            )
        )
    )
    quote = get_latest_rate("eur", "rsd", client)
    assert quote.source_currency == "EUR"
    assert quote.target_currency == "RSD"
    assert quote.rate == Decimal("117.2")
    assert quote.rate_date == date(2026, 11, 6)
    client.close()


def test_latest_reference_rate_fails_explicitly_when_provider_is_unavailable():
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503)))
    with pytest.raises(ExchangeRateError, match="Could not retrieve"):
        get_latest_rate("EUR", "RSD", client)
    client.close()


def test_same_currency_uses_one_without_a_provider_request():
    quote = get_latest_rate("RSD", "RSD")
    assert quote.rate == Decimal("1")
    assert quote.source_currency == quote.target_currency == "RSD"


@pytest.mark.parametrize(("source", "target"), [("US", "EUR"), ("USD", "EURO")])
def test_invalid_currency_codes_are_rejected(source, target):
    with pytest.raises(ExchangeRateError, match="three letters"):
        get_latest_rate(source, target)


def test_default_client_fetch_and_cache_paths(monkeypatch):
    payload = {
        "result": "success",
        "time_last_update_unix": int(datetime(2026, 11, 6, tzinfo=UTC).timestamp()),
        "rates": {"RSD": "117.2"},
    }
    calls = []

    def fetch(source):
        calls.append(source)
        return payload

    monkeypatch.setattr(exchange_rates, "_cache", {})
    monkeypatch.setattr(exchange_rates, "_fetch_payload", fetch)
    monkeypatch.setattr(exchange_rates, "monotonic", lambda: 10.0)

    assert get_latest_rate("USD", "RSD").rate == Decimal("117.2")
    assert get_latest_rate("USD", "RSD").rate == Decimal("117.2")
    assert calls == ["USD"]


def test_unsuccessful_default_fetch_is_not_cached(monkeypatch):
    monkeypatch.setattr(exchange_rates, "_cache", {})
    monkeypatch.setattr(exchange_rates, "_fetch_payload", lambda _source: {"result": "error"})
    with pytest.raises(ExchangeRateError, match="could not provide"):
        get_latest_rate("USD", "RSD")
    assert exchange_rates._cache == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"result": "error"},
        {"result": "success", "time_last_update_unix": 0, "rates": {"RSD": "0"}},
        {"result": "success", "time_last_update_unix": 0, "rates": {}},
    ],
)
def test_invalid_or_missing_daily_quotes_fail_explicitly(payload):
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)))
    with pytest.raises(ExchangeRateError):
        get_latest_rate("USD", "RSD", client)
    client.close()


def test_fetch_payload_owns_a_default_http_client(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": "success"}

    class Client:
        def __init__(self, timeout):
            assert timeout == 5

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url):
            assert url.endswith("/USD")
            return Response()

    monkeypatch.setattr(exchange_rates.httpx, "Client", Client)
    assert exchange_rates._fetch_payload("USD") == {"result": "success"}
