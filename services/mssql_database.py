"""Katalog karata iz SQL Server-a, sa istim interfejsom kao SQLite verzija.

Implementira CardLookup, pa kolekcija i uvoz rade nepromenjeni.

O pretrazi: SQL Server Full-Text Search je opciona komponenta i cesto NIJE
instalirana (standardni Docker image je nema). Ako postoji, koristi se
CONTAINS sa prefiksom; ako ne, pada na LIKE '%term%', koji nijedan indeks ne
moze da ubrza. Zato je ovaj backend osetno sporiji od lokalnog FTS5 indeksa -
vidi database/README.md.
"""

import json
import logging

from models.card import Card
from services.card_query import PagedCardResult
from services.mssql import ConnectionSettings, connect, sql

logger = logging.getLogger(__name__)

# Kolone koje pretraga gleda, isto kao u SQLite verziji.
SEARCH_COLUMNS = ("Name", "SetName", "TypeLine", "CollectorNumber")


class MssqlCardQuery(PagedCardResult):
    """Strana rezultata iz catalog.Card, preko OFFSET/FETCH."""

    def __init__(self, settings: ConnectionSettings, where_sql: str, params: tuple, order_sql: str):
        super().__init__()
        self._settings = settings
        self._where = where_sql
        self._params = tuple(params)
        self._order = order_sql

    def _count_rows(self) -> int:
        conn = connect(self._settings)
        try:
            cursor = conn.cursor()
            cursor.execute(sql(conn, f"SELECT COUNT(*) FROM catalog.Card {self._where}"), self._params)
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def _fetch_json(self, offset: int, limit: int) -> list[str]:
        conn = connect(self._settings)
        try:
            cursor = conn.cursor()
            statement = sql(conn, (
                f"SELECT ScryfallId, Name, SetCode, SetName, CollectorNumber, TypeLine, "
                f"Rarity, Cmc, Colors, ImageUrl, PriceUsd, PriceUsdFoil, PriceEur, PriceEurFoil "
                f"FROM catalog.Card {self._where} "
                f"ORDER BY {self._order} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
            ))
            cursor.execute(statement, (*self._params, offset, limit))
            return [json.dumps(_row_to_card_dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()


def _row_to_card_dict(row) -> dict:
    """Red iz catalog.Card -> oblik koji Card ocekuje."""
    colors = row[8] or "C"
    return {
        "id": str(row[0]),
        "name": row[1],
        "set": row[2],
        "set_name": row[3],
        "collector_number": row[4],
        "type_line": row[5],
        "rarity": row[6] or "",
        "cmc": float(row[7] or 0),
        "colors": [] if colors == "C" else list(colors),
        "image_url": row[9],
        "prices": {
            "usd": None if row[10] is None else str(row[10]),
            "usd_foil": None if row[11] is None else str(row[11]),
            "eur": None if row[12] is None else str(row[12]),
            "eur_foil": None if row[13] is None else str(row[13]),
        },
    }


class MssqlCardDatabase:
    """Katalog karata iz SQL Server-a."""

    def __init__(self, settings: ConnectionSettings | None = None):
        self.settings = settings or ConnectionSettings.from_env()
        self._fulltext: bool | None = None

    # -------------------------------------------------------------- helpers

    def _query(self, statement: str, params: tuple = ()):
        conn = connect(self.settings)
        try:
            cursor = conn.cursor()
            cursor.execute(sql(conn, statement), params)
            return cursor.fetchall()
        finally:
            conn.close()

    def _one_card(self, statement: str, params: tuple) -> Card | None:
        rows = self._query(statement, params)
        return Card(_row_to_card_dict(rows[0])) if rows else None

    @property
    def fulltext_available(self) -> bool:
        """Da li na serveru postoji full-text indeks nad catalog.Card."""
        if self._fulltext is None:
            try:
                rows = self._query(
                    "SELECT CONVERT(INT, SERVERPROPERTY('IsFullTextInstalled')), "
                    "(SELECT COUNT(*) FROM sys.fulltext_indexes "
                    " WHERE object_id = OBJECT_ID('catalog.Card'))"
                )
                self._fulltext = bool(rows and rows[0][0] and rows[0][1])
            except Exception as exc:
                logger.warning("Provera full-text indeksa nije uspela: %s", exc)
                self._fulltext = False

            if not self._fulltext:
                logger.info(
                    "Full-Text Search nije dostupan - pretraga koristi LIKE, "
                    "što je sporije na velikom katalogu."
                )
        return self._fulltext

    _CARD_COLUMNS = (
        "ScryfallId, Name, SetCode, SetName, CollectorNumber, TypeLine, "
        "Rarity, Cmc, Colors, ImageUrl, PriceUsd, PriceUsdFoil, PriceEur, PriceEurFoil"
    )

    # --------------------------------------------------------------- search

    def all_cards(self) -> MssqlCardQuery:
        return MssqlCardQuery(self.settings, "WHERE IsActive = 1", (), "Name, CardId")

    def search(self, query: str) -> MssqlCardQuery:
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return self.all_cards()

        if self.fulltext_available:
            expression = " AND ".join(f'"{t}*"' for t in terms)
            where = (
                "WHERE IsActive = 1 AND CONTAINS("
                f"({', '.join(SEARCH_COLUMNS)}), %s)"
            )
            return MssqlCardQuery(self.settings, where, (expression,), "Name, CardId")

        # Bez full-text-a: svaki termin mora da se nadje u spojenom tekstu.
        haystack = " + N' ' + ".join(f"ISNULL({c}, N'')" for c in SEARCH_COLUMNS)
        clauses = " AND ".join([f"{haystack} LIKE %s"] * len(terms))
        params = tuple(f"%{t}%" for t in terms)

        return MssqlCardQuery(
            self.settings, f"WHERE IsActive = 1 AND {clauses}", params, "Name, CardId"
        )

    def count(self) -> int:
        return int(self._query("SELECT COUNT(*) FROM catalog.Card WHERE IsActive = 1")[0][0])

    def load_cards(self) -> None:
        """Nista se ne ucitava u memoriju - postoji zbog istog interfejsa."""
        logger.info("SQL Server katalog: %s karata.", f"{self.count():,}")

    # --------------------------------------------------------------- lookup

    def find_exact(self, name: str, set_code: str, collector_number: str) -> Card | None:
        return self._one_card(
            f"SELECT TOP (1) {self._CARD_COLUMNS} FROM catalog.Card "
            "WHERE Name = %s AND SetCode = %s AND CollectorNumber = %s ORDER BY CardId",
            (name, str(set_code or "").lower(), str(collector_number or "")),
        )

    def find_cheapest_by_name(self, name: str) -> Card | None:
        return self._one_card(
            f"SELECT TOP (1) {self._CARD_COLUMNS} FROM catalog.Card "
            "WHERE Name = %s "
            "ORDER BY CASE WHEN PriceEur IS NULL OR PriceEur = 0 THEN 1 ELSE 0 END, "
            "PriceEur, CardId",
            (name,),
        )

    def find_by_loose_name(self, name: str) -> Card | None:
        """Uparivanje bez interpunkcije. Bez indeksirane kolone ide skeniranje,
        pa se koristi samo kao rezerva posle tacnog imena."""
        normalized = "".join(ch for ch in name.lower() if ch.isalnum())
        rows = self._query(
            f"SELECT {self._CARD_COLUMNS}, Name FROM catalog.Card "
            "WHERE LEN(Name) BETWEEN %s AND %s",
            (max(1, len(normalized) - 10), len(normalized) + 10),
        )
        for row in rows:
            candidate = "".join(ch for ch in str(row[-1]).lower() if ch.isalnum())
            if candidate == normalized:
                return Card(_row_to_card_dict(row))
        return None
