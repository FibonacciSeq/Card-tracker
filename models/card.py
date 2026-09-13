from typing import Any

from services.pricing import PricingService, calculate_card_price_rsd


class Card:

    COLOR_ORDER = {"B": 1, "U": 2, "G": 3, "R": 4, "W": 5}

    def __init__(self, raw_data: dict, is_foil: bool = False, quantity: int = 1):
        self.raw_data = raw_data
        self.quantity = raw_data.get("quantity", raw_data.get("count", quantity))
        self.name = raw_data.get("name", "Unknown Name")
        self.set_name = raw_data.get("set_name", "Unknown Set")
        self.set_code = str(raw_data.get("set", "")).lower()
        self.type_line = raw_data.get("type_line", "Unknown Type")
        self.collector_number = str(raw_data.get("collector_number", "N/A"))
        self.rarity = raw_data.get("rarity", "Unknown Rarity").capitalize()
        self.image_url = raw_data.get("image_url")
        
        if not self.image_url:
            image_uris = raw_data.get("image_uris")
            if not image_uris and "card_faces" in raw_data:
                faces = raw_data.get("card_faces", [])
                if faces and isinstance(faces[0], dict):
                    image_uris = faces[0].get("image_uris")
            
            self.image_url = image_uris.get("normal") if isinstance(image_uris, dict) else None

        try:
            self.cmc_val = float(raw_data.get("cmc", 0.0))
        except (ValueError, TypeError):
            self.cmc_val = 0.0

        self.cmc = str(int(self.cmc_val)) if self.cmc_val.is_integer() else str(self.cmc_val)

        colors = raw_data.get("colors", [])
        self.colors = "".join(colors) if colors else "C"

        prices = raw_data.get("prices") or {}

        usd_normal = prices.get("usd")
        usd_foil = prices.get("usd_foil")
        eur_normal = prices.get("eur")
        eur_foil = prices.get("eur_foil")

        eur_rate = PricingService.get_rate("EUR")

        if usd_normal is not None:
            try:
                usd_val = float(usd_normal)
                self.price_normal_val, _ = PricingService.convert_price(usd_val)
                calc_eur = usd_val * eur_rate
                self.price_normal = f"€{calc_eur:.2f}"
                self.price_normal_rsd = calculate_card_price_rsd(calc_eur)
            except (ValueError, TypeError):
                self.price_normal_val, self.price_normal_rsd, self.price_normal = 0.0, 0, "N/A"
        elif eur_normal is not None:
            try:
                eur_val = float(eur_normal)
                self.price_normal_val = eur_val
                self.price_normal = f"€{eur_normal}"
                self.price_normal_rsd = calculate_card_price_rsd(eur_val)
            except (ValueError, TypeError):
                self.price_normal_val, self.price_normal_rsd, self.price_normal = 0.0, 0, "N/A"
        else:
            self.price_normal_val = 0.0
            self.price_normal_rsd = 0
            self.price_normal = "N/A"

        # Inicijalizacija foil cene
        if usd_foil is not None:
            try:
                usd_foil_val = float(usd_foil)
                self.price_foil_val, _ = PricingService.convert_price(usd_foil_val)
                calc_eur_foil = usd_foil_val * eur_rate
                self.price_foil = f"€{calc_eur_foil:.2f}"
                self.price_foil_rsd = calculate_card_price_rsd(calc_eur_foil)
            except (ValueError, TypeError):
                self.price_foil_val, self.price_foil_rsd, self.price_foil = 0.0, 0, "N/A"
        elif eur_foil is not None:
            try:
                eur_foil_val = float(eur_foil)
                self.price_foil_val = eur_foil_val
                self.price_foil = f"€{eur_foil}"
                self.price_foil_rsd = calculate_card_price_rsd(eur_foil_val)
            except (ValueError, TypeError):
                self.price_foil_val, self.price_foil_rsd, self.price_foil = 0.0, 0, "N/A"
        else:
            self.price_foil_val = 0.0
            self.price_foil_rsd = 0
            self.price_foil = "N/A"

        self.is_foil = raw_data.get("is_foil", is_foil)

        if self.is_foil:
            self.price_numeric = self.price_foil_val if self.price_foil_val > 0 else self.price_normal_val
            self.price_rsd = self.price_foil_rsd if self.price_foil_rsd > 0 else self.price_normal_rsd
        else:
            self.price_numeric = self.price_normal_val if self.price_normal_val > 0 else self.price_foil_val
            self.price_rsd = self.price_normal_rsd if self.price_normal_rsd > 0 else self.price_foil_rsd

        self.search_str = f"{self.name} {self.set_name} {self.collector_number} {self.type_line}".lower()

    @property
    def color_sort_key(self) -> tuple[int, Any]:
        if len(self.colors) == 1 and self.colors in self.COLOR_ORDER:
            return 0, self.COLOR_ORDER[self.colors]

        if self.colors == "C":
            return 1, 0

        return 2, self.colors

    def sort_key(self):
        return self.name.lower(), self.set_name.lower(), self.cmc_val, self.color_sort_key

    def matches_query(self, query_terms: list[str]) -> bool:
        return all(term in self.search_str for term in query_terms)

    @staticmethod
    def has_valid_price(card_data: dict) -> bool:
        prices = card_data.get("prices", {})
        has_usd = prices.get("usd") is not None
        has_eur = prices.get("eur") is not None
        is_token = card_data.get("layout") == "token"
        return has_usd or has_eur or is_token

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "cmc": self.cmc,
            "cmc_val": self.cmc_val,
            "colors": self.colors,
            "type_line": self.type_line,
            "set_name": self.set_name,
            "set": self.set_code,
            "rarity": self.rarity,
            "collector_number": self.collector_number,
            "is_foil": self.is_foil,
            "image_url": self.image_url,
            "price_normal": self.price_normal,
            "price_foil": self.price_foil,
            "price_numeric": self.price_numeric,
            "price_rsd": self.price_rsd,
            "prices": self.raw_data.get("prices", {}),
            "search_str": self.search_str,
        }

    def clone(self, is_foil=None, quantity=1):
        target_foil = self.is_foil if is_foil is None else is_foil

        # raw_data ima prednost nad argumentom u __init__, pa ga ovde
        # eksplicitno prepisujemo da bi clone(is_foil=...) uvek vazio.
        raw_copy = self.raw_data.copy()
        raw_copy["is_foil"] = target_foil
        raw_copy["quantity"] = quantity

        return Card(raw_copy, is_foil=target_foil, quantity=quantity)

    def __lt__(self, other: "Card") -> bool:
        return self.sort_key() < other.sort_key()

    def identity(self) -> tuple[str, str, str, bool]:
        """Sto identifikuje jedan unos u kolekciji: printing + foil varijanta."""
        return (
            self.name.lower(),
            self.set_name.lower(),
            str(getattr(self, "collector_number", "")),
            bool(getattr(self, "is_foil", False)),
        )

    def __eq__(self, other):
        if not isinstance(other, Card):
            return NotImplemented
        return self.identity() == other.identity()

    def __hash__(self):
        return hash(self.identity())