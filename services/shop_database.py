"""Lokalna prodavnica: zalihe, porudzbine i kupci.

Dve odvojene aplikacije - `customer_app.py` i `owner_app.py` - dele isti
SQLite fajl. Sema prati ideje iz `database/03_tables_inventory.sql` i
`database/04_tables_sales.sql`, ali je namerno pojednostavljena: nema SQL
Server-a, nema staging tabela, a sve sto je potrebno za rad prodavnice je u
nekoliko tabela.

Kljucne poslovne odluke:

* kolicina na stanju se menja samo kroz `add_stock`, `set_stock` i
  isporuku porudzbine; nikada se ne pise direktno iz UI-a. Porudzbina iz
  kataloga moze napraviti novi SKU sa nula primeraka da bi vlasnik video sta
  nedostaje;
* stavke aktivne porudzbine (NEW/ORDERED/FULFILLED) ulaze u rezervaciju;
  dostupne kopije su time zasticene, a visak preko stanja je porudzbina kod
  dobavljaca koja se moze isporuciti tek kada se doda zaliha;
* tek kada vlasnik oznaci porudzbinu kao DELIVERED, roba se skida sa stanja;
* sve cene su u RSD i "zamrznute" su u trenutku porudzbine.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "cardtracker_shop.db"
DB_ENV_VAR = "CARDTRACKER_SHOP_DB"

# Bump when the local shop schema changes; migrations can branch on this.
SHOP_SCHEMA_VERSION = 1

MAX_NAME_LENGTH = 200
MAX_EMAIL_LENGTH = 254
MAX_PHONE_LENGTH = 50
MAX_NOTE_LENGTH = 2000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Sifra -> (naziv, mnozilac cene). Isto kao inv.Condition u SQL semu.
CONDITIONS = {
    "NM": ("Near Mint", 1.000),
    "LP": ("Lightly Played", 0.850),
    "MP": ("Moderately Played", 0.700),
    "HP": ("Heavily Played", 0.500),
    "DMG": ("Damaged", 0.300),
}
DEFAULT_CONDITION = "NM"

ORDER_STATUSES = {
    "NEW": "Nova",
    "ORDERED": "Karte naručene",
    "FULFILLED": "Ispunjeno",
    "DELIVERED": "Isporučeno",
    "CANCELLED": "Otkazano",
}

# Porudzbine u ovim statusima drze rezervisanu robu.
ACTIVE_STATUSES = ("NEW", "ORDERED", "FULFILLED")

# Dozvoljeni prelazi. Porudzbina ide samo napred; otkazivanje je moguce dok
# roba nije isporucena.
ALLOWED_TRANSITIONS = {
    "NEW": {"ORDERED", "FULFILLED", "DELIVERED", "CANCELLED"},
    "ORDERED": {"FULFILLED", "DELIVERED", "CANCELLED"},
    "FULFILLED": {"DELIVERED", "CANCELLED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def suggested_price_rsd(card, is_foil: bool, condition_code: str = DEFAULT_CONDITION) -> int:
    """Predlaze prodajnu cenu iz Scryfall cene, uz faktor stanja kartice."""
    if condition_code not in CONDITIONS:
        condition_code = DEFAULT_CONDITION

    if is_foil:
        base = getattr(card, "price_foil_rsd", 0) or getattr(card, "price_normal_rsd", 0)
    else:
        base = getattr(card, "price_normal_rsd", 0) or getattr(card, "price_foil_rsd", 0)

    if not base or base <= 0:
        return 0

    factor = CONDITIONS[condition_code][1]
    # Cene u aplikaciji su zaokruzene na 10 RSD; zadrzavamo isti korak i ovde.
    return int(math.ceil((base * factor) / 10.0) * 10)


MarketKey = tuple[str, bool, str, str]


def card_key(card) -> str:
    """Stabilan kljuc za jedan printing, nezavisan od naziva.

    Scryfall `id` je najbolji izbor; ako ga nema (npr. rucno napravljen Card),
    koristi se kombinacija imena, seta i kolekcijskog broja.
    """
    scryfall_id = str((getattr(card, "raw_data", {}) or {}).get("id") or "").strip().lower()
    if scryfall_id:
        return scryfall_id
    return "|".join(
        [
            str(getattr(card, "name", "")).strip().lower(),
            str(getattr(card, "set_code", "")).strip().lower(),
            str(getattr(card, "collector_number", "")).strip(),
        ]
    )


def market_key(
    card,
    is_foil: bool = False,
    condition_code: str = DEFAULT_CONDITION,
    language_code: str = "en",
) -> MarketKey:
    """Identitet jedne kupovne varijante: printing + foil + stanje + jezik."""
    return card_key(card), bool(is_foil), condition_code, language_code


def condition_label(code: str) -> str:
    return f"{code} - {CONDITIONS.get(code, (code, 1.0))[0]}"


def status_label(status: str) -> str:
    return ORDER_STATUSES.get(status, status)


def validate_contact(full_name: str, email: str, phone: str) -> None:
    """Kupac mora ostaviti ime i bar jedan nacin da ga prodavac kontaktira."""
    full_name, email, phone = (full_name or "").strip(), (email or "").strip(), (phone or "").strip()
    if not full_name:
        raise ValueError("Ime i prezime je obavezno.")
    if len(full_name) > MAX_NAME_LENGTH:
        raise ValueError(f"Ime i prezime moze imati najvise {MAX_NAME_LENGTH} znakova.")
    if not email and not phone:
        raise ValueError("Ostavite e-mail ili telefon kako bi vas prodavac mogao kontaktirati.")
    if email:
        if len(email) > MAX_EMAIL_LENGTH:
            raise ValueError(f"E-mail adresa moze imati najvise {MAX_EMAIL_LENGTH} znakova.")
        if not _EMAIL_RE.fullmatch(email):
            raise ValueError("E-mail adresa nije ispravna.")
    if phone:
        if len(phone) > MAX_PHONE_LENGTH:
            raise ValueError(f"Telefon moze imati najvise {MAX_PHONE_LENGTH} znakova.")
        if not any(ch.isdigit() for ch in phone):
            raise ValueError("Telefon mora sadrzati broj.")


@dataclass(frozen=True)
class StockItem:
    stock_id: int
    card_key: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    rarity: str
    type_line: str
    is_foil: bool
    condition_code: str
    language_code: str
    quantity: int
    reserved: int
    unit_price_rsd: int
    image_url: str

    @property
    def available(self) -> int:
        return max(0, self.quantity - self.reserved)

    @property
    def backordered(self) -> int:
        """Broj rezervisanih primeraka koji tek treba da stigne na stanje."""
        return max(0, self.reserved - self.quantity)

    @property
    def condition_name(self) -> str:
        return CONDITIONS.get(self.condition_code, (self.condition_code, 1.0))[0]

    @property
    def foil_label(self) -> str:
        return "Foil" if self.is_foil else "Non-Foil"

    @property
    def set_label(self) -> str:
        code = (self.set_code or "").upper()
        return f"{self.set_name} ({code})" if code else self.set_name


@dataclass(frozen=True)
class MarketItem:
    """Kartica koju kupac vidi na trzistu, bez obzira na trenutno stanje.

    Kada `stock_id` postoji, cena i dostupnost dolaze iz `shop_stock`. Kada ga
    nema, red je iz Scryfall kataloga i kupac ga moze naruciti kao backorder.
    """

    card_key: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    rarity: str
    type_line: str
    is_foil: bool
    condition_code: str
    language_code: str
    unit_price_rsd: int
    quantity: int
    reserved: int
    image_url: str
    stock_id: int | None = None

    @property
    def key(self) -> MarketKey:
        language = (self.language_code or "en").strip() or "en"
        return self.card_key, self.is_foil, self.condition_code, language

    @property
    def available(self) -> int:
        return max(0, self.quantity - self.reserved)

    @property
    def backordered(self) -> int:
        return max(0, self.reserved - self.quantity)

    @property
    def foil_label(self) -> str:
        return "Foil" if self.is_foil else "Non-Foil"

    @property
    def set_label(self) -> str:
        code = (self.set_code or "").upper()
        return f"{self.set_name} ({code})" if code else self.set_name

    @classmethod
    def from_stock(cls, item: StockItem) -> MarketItem:
        return cls(
            card_key=item.card_key,
            name=item.name,
            set_code=item.set_code,
            set_name=item.set_name,
            collector_number=item.collector_number,
            rarity=item.rarity,
            type_line=item.type_line,
            is_foil=item.is_foil,
            condition_code=item.condition_code,
            language_code=item.language_code,
            unit_price_rsd=item.unit_price_rsd,
            quantity=item.quantity,
            reserved=item.reserved,
            image_url=item.image_url,
            stock_id=item.stock_id,
        )

    @classmethod
    def from_card(
        cls,
        card: Any,
        *,
        is_foil: bool = False,
        condition_code: str = DEFAULT_CONDITION,
        language_code: str = "en",
        unit_price_rsd: int | None = None,
    ) -> MarketItem:
        if unit_price_rsd is None:
            unit_price_rsd = suggested_price_rsd(card, is_foil, condition_code)
        return cls(
            card_key=card_key(card),
            name=str(getattr(card, "name", "")),
            set_code=str(getattr(card, "set_code", "")),
            set_name=str(getattr(card, "set_name", "")),
            collector_number=str(getattr(card, "collector_number", "")),
            rarity=str(getattr(card, "rarity", "")),
            type_line=str(getattr(card, "type_line", "")),
            is_foil=bool(is_foil),
            condition_code=condition_code,
            language_code=language_code,
            unit_price_rsd=int(unit_price_rsd),
            quantity=0,
            reserved=0,
            image_url=str(getattr(card, "image_url", "") or ""),
            stock_id=None,
        )


@dataclass(frozen=True)
class OrderSummary:
    order_id: int
    customer_name: str
    email: str
    phone: str
    note: str
    status: str
    total_rsd: int
    created_at: str
    updated_at: str
    delivered_at: str
    line_count: int = 0

    @property
    def status_text(self) -> str:
        return status_label(self.status)


@dataclass(frozen=True)
class OrderLine:
    line_id: int
    order_id: int
    stock_id: int | None
    name: str
    set_code: str
    set_name: str
    collector_number: str
    is_foil: bool
    condition_code: str
    quantity: int
    unit_price_rsd: int
    stock_quantity: int | None = None

    @property
    def subtotal_rsd(self) -> int:
        return self.quantity * self.unit_price_rsd

    @property
    def missing_quantity(self) -> int:
        """Deo ove stavke koji trenutno nije pokriven stanjem."""
        if self.stock_quantity is None:
            return self.quantity
        return max(0, self.quantity - self.stock_quantity)

    @property
    def foil_label(self) -> str:
        return "Foil" if self.is_foil else "Non-Foil"


class ShopDatabase:
    """SQLite baza prodavnice, bezbedna za dve aplikacije nad istim fajlom."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get(DB_ENV_VAR) or DEFAULT_DB_PATH
        self._init_schema()

    # ------------------------------------------------------------------ setup

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_schema(self) -> None:
        if self.db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        conn = self._connect()
        try:
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")

            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SHOP_SCHEMA_VERSION:
                raise RuntimeError(
                    "Baza prodavnice je napravljena novijom verzijom aplikacije "
                    f"(schema v{version}, podrzano v{SHOP_SCHEMA_VERSION})."
                )

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS shop_stock (
                    stock_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_key       TEXT    NOT NULL,
                    name           TEXT    NOT NULL,
                    set_code       TEXT    NOT NULL DEFAULT '',
                    set_name       TEXT    NOT NULL DEFAULT '',
                    collector_number TEXT  NOT NULL DEFAULT '',
                    rarity         TEXT    NOT NULL DEFAULT '',
                    type_line      TEXT    NOT NULL DEFAULT '',
                    is_foil        INTEGER NOT NULL DEFAULT 0,
                    condition_code TEXT    NOT NULL DEFAULT 'NM',
                    language_code  TEXT    NOT NULL DEFAULT 'en',
                    quantity       INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    unit_price_rsd INTEGER NOT NULL DEFAULT 0 CHECK (unit_price_rsd >= 0),
                    image_url      TEXT    NOT NULL DEFAULT '',
                    raw_json       TEXT    NOT NULL DEFAULT '{}',
                    created_at     TEXT    NOT NULL,
                    updated_at     TEXT    NOT NULL,
                    UNIQUE (card_key, is_foil, condition_code, language_code)
                );

                CREATE INDEX IF NOT EXISTS idx_shop_stock_name
                    ON shop_stock (name);

                CREATE TABLE IF NOT EXISTS shop_order (
                    order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_name TEXT    NOT NULL,
                    email         TEXT    NOT NULL DEFAULT '',
                    phone         TEXT    NOT NULL DEFAULT '',
                    note          TEXT    NOT NULL DEFAULT '',
                    status        TEXT    NOT NULL DEFAULT 'NEW'
                        CHECK (status IN ('NEW', 'ORDERED', 'FULFILLED', 'DELIVERED', 'CANCELLED')),
                    total_rsd     INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT    NOT NULL,
                    updated_at    TEXT    NOT NULL,
                    delivered_at  TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_shop_order_status
                    ON shop_order (status, created_at);

                CREATE TABLE IF NOT EXISTS shop_order_line (
                    line_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id       INTEGER NOT NULL,
                    stock_id       INTEGER,
                    name           TEXT    NOT NULL,
                    set_code       TEXT    NOT NULL DEFAULT '',
                    set_name       TEXT    NOT NULL DEFAULT '',
                    collector_number TEXT  NOT NULL DEFAULT '',
                    is_foil        INTEGER NOT NULL DEFAULT 0,
                    condition_code TEXT    NOT NULL DEFAULT 'NM',
                    quantity       INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price_rsd INTEGER NOT NULL CHECK (unit_price_rsd >= 0),

                    FOREIGN KEY (order_id) REFERENCES shop_order (order_id) ON DELETE CASCADE,
                    FOREIGN KEY (stock_id) REFERENCES shop_stock (stock_id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shop_order_line_order
                    ON shop_order_line (order_id);
                CREATE INDEX IF NOT EXISTS idx_shop_order_line_stock
                    ON shop_order_line (stock_id);
                """
            )
            conn.execute(f"PRAGMA user_version = {SHOP_SCHEMA_VERSION}")
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _read(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            # IMMEDIATE uzima write lock odmah: dva kupca ne mogu istovremeno
            # da rezervisu isti poslednji primerak.
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ stock

    @staticmethod
    def _stock_from_row(row: sqlite3.Row) -> StockItem:
        return StockItem(
            stock_id=int(row["stock_id"]),
            card_key=row["card_key"],
            name=row["name"],
            set_code=row["set_code"],
            set_name=row["set_name"],
            collector_number=row["collector_number"],
            rarity=row["rarity"],
            type_line=row["type_line"],
            is_foil=bool(row["is_foil"]),
            condition_code=row["condition_code"],
            language_code=row["language_code"],
            quantity=int(row["quantity"]),
            reserved=int(row["reserved"]),
            unit_price_rsd=int(row["unit_price_rsd"]),
            image_url=row["image_url"],
        )

    def list_stock(self, query: str = "", only_available: bool = False) -> list[StockItem]:
        """Sve zalihe, sa izracunatim brojem rezervisanih primeraka."""
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        # `placeholders` is generated from the static ACTIVE_STATUSES tuple.
        sql = (
            "SELECT s.*, "
            "(SELECT COALESCE(SUM(l.quantity), 0) "
            "FROM shop_order_line AS l "
            "INNER JOIN shop_order AS o ON o.order_id = l.order_id "
            "WHERE l.stock_id = s.stock_id "
            f"AND o.status IN ({placeholders}) "
            ") AS reserved "
            "FROM shop_stock AS s"
        )
        params: list = list(ACTIVE_STATUSES)

        query = (query or "").strip()
        if query:
            sql += """
                WHERE lower(
                    s.name || ' ' || COALESCE(s.set_name, '') || ' ' ||
                    COALESCE(s.set_code, '') || ' ' || COALESCE(s.collector_number, '')
                ) LIKE ?
            """
            params.append(f"%{query.lower()}%")

        sql += """
            ORDER BY s.name COLLATE NOCASE, s.set_name COLLATE NOCASE,
                     s.collector_number, s.is_foil, s.condition_code
        """

        with self._read() as conn:
            items = [self._stock_from_row(row) for row in conn.execute(sql, params)]

        if only_available:
            items = [item for item in items if item.available > 0]
        return items

    def get_stock(self, stock_id: int) -> StockItem | None:
        for item in self.list_stock():
            if item.stock_id == int(stock_id):
                return item
        return None

    def find_stock_for_card(
        self,
        card,
        *,
        is_foil: bool = False,
        condition_code: str = DEFAULT_CONDITION,
        language_code: str = "en",
    ) -> StockItem | None:
        """Postojeci SKU za karticu, ako je vec na stanju."""
        key = card_key(card)
        for item in self.list_stock():
            if (
                item.card_key == key
                and item.is_foil == bool(is_foil)
                and item.condition_code == condition_code
                and item.language_code == language_code
            ):
                return item
        return None

    def add_stock(
        self,
        card,
        *,
        is_foil: bool = False,
        condition_code: str = DEFAULT_CONDITION,
        quantity: int = 1,
        unit_price_rsd: int | None = None,
        language_code: str = "en",
    ) -> int:
        """Dodaje primerke na stanje; isti SKU samo povecava kolicinu."""
        if condition_code not in CONDITIONS:
            raise ValueError("Nepoznato stanje kartice.")
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError("Kolicina mora biti veca od nule.")

        if unit_price_rsd is None:
            unit_price_rsd = suggested_price_rsd(card, is_foil, condition_code)
        unit_price_rsd = int(unit_price_rsd)
        if unit_price_rsd < 0:
            raise ValueError("Cena ne moze biti negativna.")

        key = card_key(card)
        now = _now()
        raw_json = json.dumps(getattr(card, "raw_data", {}) or {}, ensure_ascii=False, default=str)

        with self._transaction() as conn:
            existing = conn.execute(
                """
                SELECT stock_id, quantity FROM shop_stock
                WHERE card_key = ? AND is_foil = ? AND condition_code = ? AND language_code = ?
                """,
                (key, int(bool(is_foil)), condition_code, language_code),
            ).fetchone()

            if existing:
                stock_id = int(existing["stock_id"])
                conn.execute(
                    """
                    UPDATE shop_stock
                    SET quantity = quantity + ?, unit_price_rsd = ?,
                        name = ?, set_code = ?, set_name = ?, collector_number = ?,
                        rarity = ?, type_line = ?, image_url = ?, raw_json = ?, updated_at = ?
                    WHERE stock_id = ?
                    """,
                    (
                        quantity,
                        unit_price_rsd,
                        getattr(card, "name", ""),
                        getattr(card, "set_code", ""),
                        getattr(card, "set_name", ""),
                        str(getattr(card, "collector_number", "")),
                        getattr(card, "rarity", ""),
                        getattr(card, "type_line", ""),
                        getattr(card, "image_url", "") or "",
                        raw_json,
                        now,
                        stock_id,
                    ),
                )
                return stock_id

            cursor = conn.execute(
                """
                INSERT INTO shop_stock (
                    card_key, name, set_code, set_name, collector_number, rarity,
                    type_line, is_foil, condition_code, language_code, quantity,
                    unit_price_rsd, image_url, raw_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    getattr(card, "name", ""),
                    getattr(card, "set_code", ""),
                    getattr(card, "set_name", ""),
                    str(getattr(card, "collector_number", "")),
                    getattr(card, "rarity", ""),
                    getattr(card, "type_line", ""),
                    int(bool(is_foil)),
                    condition_code,
                    language_code,
                    quantity,
                    unit_price_rsd,
                    getattr(card, "image_url", "") or "",
                    raw_json,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def set_stock(self, stock_id: int, *, quantity: int | None = None, unit_price_rsd: int | None = None) -> None:
        """Apsolutna izmena kolicine i/ili cene postojeceg SKU-a."""
        with self._transaction() as conn:
            row = conn.execute("SELECT quantity FROM shop_stock WHERE stock_id = ?", (stock_id,)).fetchone()
            if row is None:
                raise ValueError("Stavka na stanju ne postoji.")

            if quantity is not None:
                quantity = int(quantity)
                if quantity < 0:
                    raise ValueError("Kolicina ne moze biti negativna.")

                current_quantity = int(row["quantity"])
                reserved = self._reserved_quantity(conn, stock_id)
                # Ako je SKU vec kratak zbog porudzbina kod dobavljaca,
                # dozvoli cuvanje iste kolicine (npr. samo izmenu cene).
                if quantity < reserved and quantity < current_quantity:
                    raise ValueError(
                        f"Na stanju je vec rezervisano {reserved} primeraka. Kolicina ne moze biti manja od toga."
                    )

            if unit_price_rsd is not None:
                unit_price_rsd = int(unit_price_rsd)
                if unit_price_rsd < 0:
                    raise ValueError("Cena ne moze biti negativna.")

            conn.execute(
                """
                UPDATE shop_stock
                SET quantity = COALESCE(?, quantity),
                    unit_price_rsd = COALESCE(?, unit_price_rsd),
                    updated_at = ?
                WHERE stock_id = ?
                """,
                (quantity, unit_price_rsd, _now(), stock_id),
            )

    def remove_stock(self, stock_id: int) -> None:
        with self._transaction() as conn:
            row = conn.execute("SELECT stock_id FROM shop_stock WHERE stock_id = ?", (stock_id,)).fetchone()
            if row is None:
                raise ValueError("Stavka na stanju ne postoji.")

            reserved = self._reserved_quantity(conn, stock_id)
            if reserved > 0:
                raise ValueError(
                    f"Stavka ima {reserved} rezervisanih primeraka u aktivnim porudzbinama i ne moze se obrisati."
                )

            conn.execute("DELETE FROM shop_stock WHERE stock_id = ?", (stock_id,))

    @staticmethod
    def _reserved_quantity(conn: sqlite3.Connection, stock_id: int) -> int:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        sql = (
            "SELECT COALESCE(SUM(l.quantity), 0) "
            "FROM shop_order_line AS l "
            "INNER JOIN shop_order AS o ON o.order_id = l.order_id "
            f"WHERE l.stock_id = ? AND o.status IN ({placeholders})"
        )
        row = conn.execute(sql, (stock_id, *ACTIVE_STATUSES)).fetchone()
        return int(row[0])

    def stock_stats(self) -> dict:
        items = self.list_stock()
        return {
            "rows": len(items),
            "units": sum(item.quantity for item in items),
            "reserved": sum(item.reserved for item in items),
            "backordered": sum(item.backordered for item in items),
            "available": sum(item.available for item in items),
            "value_rsd": sum(item.quantity * item.unit_price_rsd for item in items),
        }

    # ----------------------------------------------------------------- orders

    @staticmethod
    def _order_from_row(row: sqlite3.Row) -> OrderSummary:
        keys = row.keys()
        return OrderSummary(
            order_id=int(row["order_id"]),
            customer_name=row["customer_name"],
            email=row["email"],
            phone=row["phone"],
            note=row["note"],
            status=row["status"],
            total_rsd=int(row["total_rsd"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            delivered_at=row["delivered_at"] or "",
            line_count=int(row["line_count"]) if "line_count" in keys else 0,
        )

    @staticmethod
    def _insert_order_line(
        conn: sqlite3.Connection,
        order_id: int,
        row: sqlite3.Row,
        quantity: int,
    ) -> int:
        unit_price = int(row["unit_price_rsd"])
        conn.execute(
            """
            INSERT INTO shop_order_line (
                order_id, stock_id, name, set_code, set_name, collector_number,
                is_foil, condition_code, quantity, unit_price_rsd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                int(row["stock_id"]),
                row["name"],
                row["set_code"],
                row["set_name"],
                row["collector_number"],
                row["is_foil"],
                row["condition_code"],
                quantity,
                unit_price,
            ),
        )
        return quantity * unit_price

    def create_order(
        self,
        customer_name: str,
        email: str,
        phone: str,
        note: str,
        items: list[tuple[int, int]] | dict[int, int],
    ) -> int:
        """Pravi porudzbinu i evidentira rezervaciju.

        `items` je lista/grupisanje (stock_id, kolicina). Cene se uzimaju iz
        trenutnog stanja i kopiraju u stavke, tako da kasnija promena cene ne
        menja vec poslatu porudzbinu.

        Dozvoljeno je naruciti i vise od trenutnog stanja. Takav visak ostaje
        vezan za SKU i bice isporucen kada vlasnik doda dovoljno primeraka.
        """
        customer_name = (customer_name or "").strip()
        email = (email or "").strip()
        phone = (phone or "").strip()
        note = (note or "").strip()
        validate_contact(customer_name, email, phone)
        if len(note) > MAX_NOTE_LENGTH:
            raise ValueError(f"Napomena moze imati najvise {MAX_NOTE_LENGTH} znakova.")

        quantities: dict[int, int] = {}
        pairs = items.items() if isinstance(items, dict) else items
        for stock_id, quantity in pairs:
            stock_id, quantity = int(stock_id), int(quantity)
            if quantity <= 0:
                raise ValueError("Kolicina u porudzbini mora biti veca od nule.")
            quantities[stock_id] = quantities.get(stock_id, 0) + quantity

        if not quantities:
            raise ValueError("Porudzbina nema nijednu karticu.")

        now = _now()
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO shop_order
                    (customer_name, email, phone, note, status, total_rsd, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'NEW', 0, ?, ?)
                """,
                (customer_name, email, phone, note, now, now),
            )
            order_id = int(cursor.lastrowid)
            total = 0

            for stock_id, quantity in quantities.items():
                row = conn.execute("SELECT * FROM shop_stock WHERE stock_id = ?", (stock_id,)).fetchone()
                if row is None:
                    raise ValueError("Neka kartica iz porudzbine vise nije u ponudi.")

                # Kolicina moze da predje trenutno stanje. Ostatak se cuva
                # kao porudzbina kod dobavljaca i ne moze se isporuciti dok
                # vlasnik ne doda dovoljno primeraka na stanje.
                total += self._insert_order_line(conn, order_id, row, quantity)

            conn.execute(
                "UPDATE shop_order SET total_rsd = ?, updated_at = ? WHERE order_id = ?",
                (total, _now(), order_id),
            )
            return order_id

    @staticmethod
    def _ensure_stock_row(conn: sqlite3.Connection, item: MarketItem) -> sqlite3.Row:
        """Vraca SKU za izabranu varijantu, a po potrebi ga pravi sa 0 komada."""
        if item.condition_code not in CONDITIONS:
            raise ValueError("Nepoznato stanje kartice.")
        language_code = (item.language_code or "en").strip() or "en"
        unit_price_rsd = int(item.unit_price_rsd)
        if unit_price_rsd < 0:
            raise ValueError("Cena ne moze biti negativna.")

        row = conn.execute(
            """
            SELECT * FROM shop_stock
            WHERE card_key = ? AND is_foil = ? AND condition_code = ? AND language_code = ?
            """,
            (item.card_key, int(bool(item.is_foil)), item.condition_code, language_code),
        ).fetchone()
        if row is not None:
            return row

        now = _now()
        cursor = conn.execute(
            """
            INSERT INTO shop_stock (
                card_key, name, set_code, set_name, collector_number, rarity,
                type_line, is_foil, condition_code, language_code, quantity,
                unit_price_rsd, image_url, raw_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, '{}', ?, ?)
            """,
            (
                item.card_key,
                item.name,
                item.set_code,
                item.set_name,
                item.collector_number,
                item.rarity,
                item.type_line,
                int(bool(item.is_foil)),
                item.condition_code,
                language_code,
                unit_price_rsd,
                item.image_url,
                now,
                now,
            ),
        )
        stock_id = cursor.lastrowid
        if stock_id is None:
            raise RuntimeError("Nova stavka na stanju nije sacuvana.")
        row = conn.execute("SELECT * FROM shop_stock WHERE stock_id = ?", (int(stock_id),)).fetchone()
        if row is None:
            raise RuntimeError("Nova stavka na stanju nije sacuvana.")
        return row

    def create_market_order(
        self,
        customer_name: str,
        email: str,
        phone: str,
        note: str,
        items: Sequence[tuple[MarketItem, int]],
    ) -> int:
        """Porudzbina iz celog kataloga; nedostupne kartice dobijaju SKU sa 0 komada."""
        customer_name = (customer_name or "").strip()
        email = (email or "").strip()
        phone = (phone or "").strip()
        note = (note or "").strip()
        validate_contact(customer_name, email, phone)
        if len(note) > MAX_NOTE_LENGTH:
            raise ValueError(f"Napomena moze imati najvise {MAX_NOTE_LENGTH} znakova.")

        quantities: dict[MarketKey, tuple[MarketItem, int]] = {}
        for item, requested in items:
            quantity = int(requested)
            if quantity <= 0:
                raise ValueError("Kolicina u porudzbini mora biti veca od nule.")
            if item.condition_code not in CONDITIONS:
                raise ValueError("Nepoznato stanje kartice.")

            key = item.key
            if key in quantities:
                existing, current = quantities[key]
                quantities[key] = (existing, current + quantity)
            else:
                quantities[key] = (item, quantity)

        if not quantities:
            raise ValueError("Porudzbina nema nijednu karticu.")

        now = _now()
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO shop_order
                    (customer_name, email, phone, note, status, total_rsd, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'NEW', 0, ?, ?)
                """,
                (customer_name, email, phone, note, now, now),
            )
            order_id = int(cursor.lastrowid)
            total = 0

            for item, quantity in quantities.values():
                row = self._ensure_stock_row(conn, item)
                total += self._insert_order_line(conn, order_id, row, quantity)

            conn.execute(
                "UPDATE shop_order SET total_rsd = ?, updated_at = ? WHERE order_id = ?",
                (total, _now(), order_id),
            )
            return order_id

    def list_orders(self, status: str | None = None) -> list[OrderSummary]:
        sql = """
            SELECT o.*, COUNT(l.line_id) AS line_count
            FROM shop_order AS o
            LEFT JOIN shop_order_line AS l ON l.order_id = o.order_id
        """
        params: tuple = ()
        if status:
            sql += " WHERE o.status = ?"
            params = (status,)
        sql += " GROUP BY o.order_id ORDER BY o.created_at DESC, o.order_id DESC"

        with self._read() as conn:
            return [self._order_from_row(row) for row in conn.execute(sql, params)]

    def get_order(self, order_id: int) -> OrderSummary | None:
        with self._read() as conn:
            row = conn.execute(
                """
                SELECT o.*, COUNT(l.line_id) AS line_count
                FROM shop_order AS o
                LEFT JOIN shop_order_line AS l ON l.order_id = o.order_id
                WHERE o.order_id = ?
                GROUP BY o.order_id
                """,
                (order_id,),
            ).fetchone()
        return self._order_from_row(row) if row else None

    def get_order_lines(self, order_id: int) -> list[OrderLine]:
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT l.*, s.quantity AS stock_quantity
                FROM shop_order_line l
                LEFT JOIN shop_stock s ON s.stock_id = l.stock_id
                WHERE l.order_id = ?
                ORDER BY l.line_id
                """,
                (order_id,),
            ).fetchall()

        return [
            OrderLine(
                line_id=int(row["line_id"]),
                order_id=int(row["order_id"]),
                stock_id=row["stock_id"],
                name=row["name"],
                set_code=row["set_code"],
                set_name=row["set_name"],
                collector_number=row["collector_number"],
                is_foil=bool(row["is_foil"]),
                condition_code=row["condition_code"],
                quantity=int(row["quantity"]),
                unit_price_rsd=int(row["unit_price_rsd"]),
                stock_quantity=int(row["stock_quantity"]) if row["stock_quantity"] is not None else None,
            )
            for row in rows
        ]

    def allowed_statuses(self, order_id: int) -> set[str]:
        order = self.get_order(order_id)
        return set(ALLOWED_TRANSITIONS.get(order.status, set())) if order else set()

    def update_order_status(self, order_id: int, new_status: str) -> None:
        if new_status not in ORDER_STATUSES:
            raise ValueError("Nepoznat status porudzbine.")

        with self._transaction() as conn:
            order = conn.execute("SELECT status FROM shop_order WHERE order_id = ?", (order_id,)).fetchone()
            if order is None:
                raise ValueError("Porudzbina ne postoji.")

            current = order["status"]
            if current == new_status:
                return
            if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"Status '{status_label(current)}' ne moze preci u '{status_label(new_status)}'.")

            if new_status == "DELIVERED":
                lines = conn.execute(
                    "SELECT stock_id, name, quantity FROM shop_order_line WHERE order_id = ?",
                    (order_id,),
                ).fetchall()

                for line in lines:
                    stock_id = line["stock_id"]
                    if stock_id is None:
                        raise ValueError(f"Kartica '{line['name']}' vise nema stavku na stanju; isporuka nije moguca.")
                    stock = conn.execute("SELECT quantity FROM shop_stock WHERE stock_id = ?", (stock_id,)).fetchone()
                    if stock is None or int(stock["quantity"]) < int(line["quantity"]):
                        raise ValueError(
                            f"Nema dovoljno primeraka za '{line['name']}' da bi porudzbina bila isporucena."
                        )

                for line in lines:
                    conn.execute(
                        """
                        UPDATE shop_stock
                        SET quantity = quantity - ?, updated_at = ?
                        WHERE stock_id = ?
                        """,
                        (int(line["quantity"]), _now(), line["stock_id"]),
                    )

            delivered_at = _now() if new_status == "DELIVERED" else None
            conn.execute(
                """
                UPDATE shop_order
                SET status = ?, updated_at = ?, delivered_at = COALESCE(?, delivered_at)
                WHERE order_id = ?
                """,
                (new_status, _now(), delivered_at, order_id),
            )

    def order_stats(self) -> dict:
        orders = self.list_orders()
        return {
            "total": len(orders),
            "new": sum(1 for order in orders if order.status == "NEW"),
            "open": sum(1 for order in orders if order.status in ("NEW", "ORDERED", "FULFILLED")),
            "delivered": sum(1 for order in orders if order.status == "DELIVERED"),
            "revenue_rsd": sum(order.total_rsd for order in orders if order.status == "DELIVERED"),
        }
