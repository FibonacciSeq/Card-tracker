"""Lenja sekvenca rezultata pretrage.

FastCardList prikazuje 10 kartica po strani, ali je do sada dobijao listu sa
*svim* karticama. Ovaj objekat se ponasa kao lista (len + slice), a redove
dovlaci iz SQLite-a tek kada zatrebaju.
"""

import json
import sqlite3
from collections.abc import Sequence

from models.card import Card


class CardQueryResult(Sequence):
    def __init__(self, db_path: str, where_sql: str = "", params: tuple = (), order_sql: str = "cards.id"):
        self._db_path = db_path
        self._where = where_sql
        self._params = tuple(params)
        self._order = order_sql
        self._count: int | None = None
        self._page_cache: tuple[int, int, list[Card]] | None = None

    def _connect(self) -> sqlite3.Connection:
        # Nova konekcija po pozivu: SQLite konekcije nisu deljive medju nitima.
        return sqlite3.connect(self._db_path)

    def __len__(self) -> int:
        if self._count is None:
            conn = self._connect()
            try:
                sql = f"SELECT COUNT(*) FROM cards {self._where}"
                self._count = conn.execute(sql, self._params).fetchone()[0]
            finally:
                conn.close()
        return self._count

    def _fetch(self, offset: int, limit: int) -> list[Card]:
        if limit <= 0:
            return []

        if self._page_cache is not None:
            cached_offset, cached_limit, cached_rows = self._page_cache
            if cached_offset == offset and cached_limit == limit:
                return cached_rows

        conn = self._connect()
        try:
            sql = (
                f"SELECT cards.raw_json FROM cards {self._where} "
                f"ORDER BY {self._order} LIMIT ? OFFSET ?"
            )
            rows = conn.execute(sql, (*self._params, limit, offset)).fetchall()
        finally:
            conn.close()

        cards = []
        for (raw_json,) in rows:
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
