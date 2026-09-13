"""Jedinstveni interfejs za trazenje karata u bazi.

Do sada su i kolekcija i uvoz gradili sopstvene mape nad *celom* bazom u
memoriji. Ovaj protokol dozvoljava da SQLite verzija radi isti posao preko
indeksa, a da testovi i JSONL backend koriste in-memory implementaciju.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CardLookup(Protocol):
    def find_exact(self, name: str, set_code: str, collector_number: str) -> Any | None:
        """Tacno to izdanje, ili None."""

    def find_cheapest_by_name(self, name: str) -> Any | None:
        """Najjeftinije izdanje karte sa datim imenom, ili None."""

    def find_by_loose_name(self, name: str) -> Any | None:
        """Kao gore, ali ignorise interpunkciju i razmake."""


def normalize_name(name: str) -> str:
    """Ime svedeno na slova i cifre: "Jace, the Mind Sculptor" -> "jacethemindsculptor"."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _as_dict(card: Any) -> dict:
    return card.to_dict() if hasattr(card, "to_dict") else card


def _price_of(card: Any) -> float:
    try:
        return float(_as_dict(card).get("price_numeric", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


class InMemoryCardLookup:
    """CardLookup nad obicnom listom karata (ili dict-ova)."""

    def __init__(self, cards: list[Any]):
        self._cards = list(cards)
        self._exact: dict[tuple[str, str, str], Any] = {}
        self._cheapest: dict[str, Any] = {}
        self._loose: dict[str, Any] = {}

        for card in self._cards:
            data = _as_dict(card)
            name_key = data.get("name", "").lower()

            key = (
                name_key,
                str(data.get("set") or data.get("set_name") or "").lower(),
                str(data.get("collector_number", "")),
            )
            self._exact.setdefault(key, card)

            for bucket, key in ((self._cheapest, name_key), (self._loose, normalize_name(name_key))):
                current = bucket.get(key)
                if current is None:
                    bucket[key] = card
                    continue

                price, current_price = _price_of(card), _price_of(current)
                if price > 0 and (current_price == 0 or price < current_price):
                    bucket[key] = card

    def find_exact(self, name: str, set_code: str, collector_number: str) -> Any | None:
        key = (name.lower(), str(set_code or "").lower(), str(collector_number or ""))
        return self._exact.get(key)

    def find_cheapest_by_name(self, name: str) -> Any | None:
        return self._cheapest.get(name.lower())

    def find_by_loose_name(self, name: str) -> Any | None:
        return self._loose.get(normalize_name(name))

    def all_cards(self) -> list[Any]:
        return self._cards


def as_lookup(source: Any) -> CardLookup:
    """Prihvata CardLookup, objekat sa .cards, ili obicnu listu."""
    if hasattr(source, "find_exact") and hasattr(source, "find_cheapest_by_name"):
        return source
    if hasattr(source, "cards"):
        return InMemoryCardLookup(source.cards)
    return InMemoryCardLookup(source)
