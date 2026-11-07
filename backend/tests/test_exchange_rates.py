from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

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
