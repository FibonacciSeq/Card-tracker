"""Zajednicki fixtures.

Kljucna stvar: kursevi valuta se pinuju pre nego sto se napravi ijedan Card,
tako da testovi nikada ne diraju mrezu i uvek daju iste brojeve.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.pricing import PricingService  # noqa: E402

# 1 USD = 0.90 EUR, 1 USD = 117 RSD  ->  1 EUR = 130 RSD
PINNED_RATES = {"EUR": 0.90, "RSD": 117.0}
EUR_TO_RSD = PINNED_RATES["RSD"] / PINNED_RATES["EUR"]


@pytest.fixture(autouse=True)
def pinned_rates(monkeypatch):
    """Sprecava HTTP pozive i cini cene predvidivim."""
    monkeypatch.setattr(PricingService, "_rates_cache", dict(PINNED_RATES))
    monkeypatch.setattr(PricingService, "_last_fetch_date", datetime.now().date())
    monkeypatch.setattr(PricingService, "_last_attempt", datetime.now())

    def _boom(*args, **kwargs):
        raise AssertionError("Test je pokusao da pozove mrezu")

    monkeypatch.setattr("services.pricing.requests.get", _boom)
    return PINNED_RATES


@pytest.fixture
def bolt_data():
    return {
        "name": "Lightning Bolt",
        "set_name": "Limited Edition Beta",
        "set": "leb",
        "collector_number": "161",
        "type_line": "Instant",
        "rarity": "common",
        "cmc": 1.0,
        "colors": ["R"],
        "image_uris": {"normal": "https://img.example/bolt.jpg"},
        "prices": {"usd": "5.00", "usd_foil": "50.00"},
    }


@pytest.fixture
def forest_data():
    return {
        "name": "Forest",
        "set_name": "Bloomburrow",
        "set": "blb",
        "collector_number": "280",
        "type_line": "Basic Land — Forest",
        "rarity": "common",
        "cmc": 0,
        "colors": [],
        "prices": {"usd": "0.10", "usd_foil": "0.30"},
    }


class FakeDatabase:
    """Minimalni stand-in za CardDatabase / SQLiteCardDatabase."""

    def __init__(self, cards):
        self.cards = list(cards)

    def search(self, query: str):
        terms = query.strip().lower().split()
        if not terms:
            return self.cards
        return [c for c in self.cards if c.matches_query(terms)]


@pytest.fixture
def fake_db(bolt_data, forest_data):
    from models.card import Card

    return FakeDatabase([Card(bolt_data), Card(forest_data)])
