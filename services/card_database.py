import json
import logging

from downloader import ScryfallDownloader
from models.card import Card
from services.card_lookup import InMemoryCardLookup

logger = logging.getLogger(__name__)


class CardDatabase:
    """Ucitava Scryfall bazu direktno iz JSONL fajla (bez SQLite indeksa)."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.cards: list[Card] = []
        self._lookup = InMemoryCardLookup([])

    def load_cards(self) -> None:
        self.cards = []
        try:
            with open(self.filepath, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue

                    card_data = json.loads(line)

                    if Card.has_valid_price(card_data):
                        self.cards.append(Card(card_data))

            self._lookup = InMemoryCardLookup(self.cards)
            logger.info(f"Uspešno učitano {len(self.cards)} karata u bazu.")
        except Exception as e:
            logger.error(f"Greška pri učitavanju baze: {e}")

    def update_from_scryfall(self) -> bool:
        downloader = ScryfallDownloader()
        success = downloader.download_and_extract(self.filepath)

        if success:
            self.load_cards()

        return success

    def all_cards(self) -> list[Card]:
        return self.cards

    def find_exact(self, name: str, set_code: str, collector_number: str) -> Card | None:
        return self._lookup.find_exact(name, set_code, collector_number)

    def find_cheapest_by_name(self, name: str) -> Card | None:
        return self._lookup.find_cheapest_by_name(name)

    def count(self) -> int:
        return len(self.cards)

    def search(self, query: str) -> list[Card]:
        query_terms = query.strip().lower().split()

        if not query_terms:
            return self.cards

        return [card for card in self.cards if card.matches_query(query_terms)]
