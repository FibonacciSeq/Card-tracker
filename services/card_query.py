"""Lenja sekvenca rezultata pretrage.

FastCardList prikazuje 10 kartica po strani, ali je do sada dobijao listu sa
*svim* karticama. Ovi objekti se ponasaju kao lista (len + slice), a redove
dovlace iz baze tek kada zatrebaju.

Baza se razlikuje po dijalektu za paginaciju, pa je zajednicki deo u
PagedCardResult, a svaki backend implementira samo dva metoda.
"""

import json
import sqlite3
from abc import abstractmethod
from collections.abc import Sequence

from models.card import Card


class PagedCardResult(Sequence):
    """Broji redove i dovlaci ih po stranama; backend radi sam upit."""

    def __init__(self):
        self._count: int | None = None
        self._page_cache: tuple[int, int, list[Card]] | None = None

    @abstractmethod
    def _count_rows(self) -> int:
        """Ukupan broj redova koji odgovaraju upitu."""

    @abstractmethod
    def _fetch_json(self, offset: int, limit: int) -> list[str]:
        """raw_json za traženu stranu."""

    def __len__(self) -> int:
        if self._count is None:
            self._count = self._count_rows()
        return self._count

    def _fetch(self, offset: int, limit: int) -> list[Card]:
        if limit <= 0:
            return []

        if self._page_cache is not None:
            cached_offset, cached_limit, cached_rows = self._page_cache
            if cached_offset == offset and cached_limit == limit:
                return cached_rows

        cards = []
        for raw_json in self._fetch_json(offset, limit):
            try:
                cards.append(Card(json.loads(raw_json)))
            except Exception:
                continue

        self._page_cache = (offset, limit, cards)
        return cards

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                return self._fetch(0, len(self))[index]
            return self._fetch(start, max(0, stop - start))

        if index < 0:
            index += len(self)
        page = self._fetch(index, 1)
        if not page:
            raise IndexError("card index out of range")
        return page[0]


class CardQueryResult(PagedCardResult):
    """Rezultat nad lokalnom SQLite bazom."""

    def __init__(self, db_path: str, where_sql: str = "", params: tuple = (), order_sql: str = "cards.id"):
        super().__init__()
        self._db_path = db_path
        self._where = where_sql
        self._params = tuple(params)
        self._order = order_sql

    def _connect(self) -> sqlite3.Connection:
        # Nova konekcija po pozivu: SQLite konekcije nisu deljive medju nitima.
        return sqlite3.connect(self._db_path)

    def _count_rows(self) -> int:
        conn = self._connect()
        try:
            return conn.execute(f"SELECT COUNT(*) FROM cards {self._where}", self._params).fetchone()[0]
        finally:
            conn.close()

    def _fetch_json(self, offset: int, limit: int) -> list[str]:
        conn = self._connect()
        try:
            sql = (
                f"SELECT cards.raw_json FROM cards {self._where} "
                f"ORDER BY {self._order} LIMIT ? OFFSET ?"
            )
            return [row[0] for row in conn.execute(sql, (*self._params, limit, offset))]
        finally:
            conn.close()
