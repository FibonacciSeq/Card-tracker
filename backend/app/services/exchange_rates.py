"""Latest published daily exchange rates from Exchange Rate API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic

import httpx

API_URL = "https://open.er-api.com/v6/latest"
CACHE_MAX_AGE_SECONDS = 23 * 60 * 60
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = Lock()


class ExchangeRateError(Exception):
    """A current reference rate could not be retrieved or validated."""


@dataclass(frozen=True)
class ExchangeRate:
    source_currency: str
    target_currency: str
    rate: Decimal
    rate_date: date


def get_latest_rate(source_currency: str, target_currency: str, client: httpx.Client | None = None) -> ExchangeRate:
    source = source_currency.upper()
    target = target_currency.upper()
    if any(len(code) != 3 or not code.isalpha() for code in (source, target)):
        raise ExchangeRateError("Currency codes must contain three letters.")
    if source == target:
        return ExchangeRate(source, target, Decimal("1"), date.today())

    try:
        if client is None:
            with _cache_lock:
                cached = _cache.get(source)
                if cached is not None and monotonic() - cached[0] < CACHE_MAX_AGE_SECONDS:
                    payload = cached[1]
                else:
                    payload = _fetch_payload(source)
                    if payload.get("result") == "success":
                        _cache[source] = (monotonic(), payload)
        else:
            payload = _fetch_payload(source, client)
        if payload.get("result") != "success":
            raise ExchangeRateError("The daily exchange-rate service could not provide a current reference rate.")
        rate = Decimal(str(payload["rates"][target]))
        rate_date = datetime.fromtimestamp(int(payload["time_last_update_unix"]), UTC).date()
        if not rate.is_finite() or rate <= 0:
            raise InvalidOperation
    except ExchangeRateError:
        raise
    except httpx.HTTPError as exc:
        raise ExchangeRateError(
            f"Could not retrieve the latest {source}/{target} reference rate. Try the CSV check again later."
        ) from exc
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise ExchangeRateError(
            f"The exchange-rate service returned no valid {source}/{target} reference rate."
        ) from exc

    return ExchangeRate(source, target, rate, rate_date)


def _fetch_payload(source_currency: str, client: httpx.Client | None = None) -> dict:
    if client is None:
        with httpx.Client(timeout=5) as http_client:
            response = http_client.get(f"{API_URL}/{source_currency}")
    else:
        response = client.get(f"{API_URL}/{source_currency}")
    response.raise_for_status()
    return response.json()
