import json
import logging
import os
import re
import sqlite3

from downloader import ScryfallDownloader
from models.card import Card
from services.card_lookup import normalize_name
from services.card_query import CardQueryResult

logger = logging.getLogger(__name__)

# Referentni kurs samo za *poredjenje* cena u indeksu. Ne koristi se za prikaz,
# pa indeks ostaje deterministican bez obzira na dnevni kurs.
_EUR_PER_USD_REFERENCE = 0.92

_FTS_COLUMNS = "name, set_name, type_line, collector_number"

# Podici kad se sema promeni: stari indeks se tada odbacuje i gradi ponovo
# (izveden je iz JSONL-a, pa nista trajno ne gubimo).
SCHEMA_VERSION = 2


class SQLiteCardDatabase:
    """Scryfall baza u SQLite-u, sa FTS pretragom i direktnim lookup-ovima."""

    BATCH_SIZE = 5000

    def __init__(self, db_path="scryfall.db", jsonl_path="scryfall_default_cards.jsonl"):
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self._init_db()

    # ------------------------------------------------------------------ schema

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._connect()
        try:
            cursor = conn.cursor()

            version = cursor.execute("PRAGMA user_version").fetchone()[0]
            if version and version != SCHEMA_VERSION:
                logger.info("Stara šema indeksa (v%s) - gradim ponovo.", version)
                for table in ("cards_trigram", "cards_fts", "cards"):
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    name_lower TEXT,
                    set_name TEXT,
                    set_code TEXT,
                    collector_number TEXT,
                    type_line TEXT,
                    name_alnum TEXT,
                    price_sort REAL,
                    raw_json TEXT
                )
            """)

            # Lookup po imenu (najjeftinije izdanje) i po tacnom izdanju.
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name_lower, price_sort)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_alnum ON cards(name_alnum, price_sort)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_cards_exact "
                "ON cards(name_lower, set_code, collector_number)"
            )

            # Prefiks pretraga (brza, rangirana preko bm25).
            cursor.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
                    {_FTS_COLUMNS},
                    content='cards', content_rowid='id'
                )
            """)

            # Fallback za pretragu usred reci ("ning" -> Lightning).
            cursor.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS cards_trigram USING fts5(
                    {_FTS_COLUMNS},
                    content='cards', content_rowid='id', tokenize='trigram'
                )
            """)

            cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ import

    @staticmethod
    def _price_sort(card_data: dict) -> float:
        prices = card_data.get("prices") or {}
        usd, eur = prices.get("usd"), prices.get("eur")
        try:
            if usd is not None:
                return float(usd) * _EUR_PER_USD_REFERENCE
            if eur is not None:
                return float(eur)
        except (TypeError, ValueError):
            pass
        return 0.0

    @classmethod
    def _row_for(cls, card_data: dict) -> tuple:
        name = card_data.get("name", "")
        return (
            name,
            name.lower(),
            card_data.get("set_name", ""),
            str(card_data.get("set", "")).lower(),
            str(card_data.get("collector_number", "")),
            card_data.get("type_line", ""),
            normalize_name(name),
            cls._price_sort(card_data),
            json.dumps(card_data),
        )

    def _is_empty(self, conn: sqlite3.Connection) -> bool:
        return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0

    def _import_jsonl(self, conn: sqlite3.Connection) -> None:
        if not os.path.exists(self.jsonl_path):
            logger.error("JSONL fajl '%s' nije pronađen u root folderu!", self.jsonl_path)
            return

        logger.info("Pronađen JSONL fajl: %s. Inicijalizujem SQLite bazu...", self.jsonl_path)
        cursor = conn.cursor()
        insert_sql = (
            "INSERT INTO cards "
            "(name, name_lower, set_name, set_code, collector_number, type_line, name_alnum, price_sort, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )

        batch = []
        with open(self.jsonl_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    card_data = json.loads(line)
                except ValueError:
                    continue

                if not Card.has_valid_price(card_data):
                    continue

                batch.append(self._row_for(card_data))

                if len(batch) >= self.BATCH_SIZE:
                    cursor.executemany(insert_sql, batch)
                    conn.commit()
                    batch = []

        if batch:
            cursor.executemany(insert_sql, batch)
            conn.commit()

        for table in ("cards_fts", "cards_trigram"):
            cursor.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        conn.commit()

    def load_cards(self) -> None:
        """Gradi indeks ako je prazan. Karte se vise ne drze u memoriji."""
        conn = self._connect()
        try:
            if self._is_empty(conn):
                self._import_jsonl(conn)
            total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        finally:
            conn.close()

        logger.info("Baza spremna: %s karata u SQLite indeksu.", f"{total:,}")

    def update_from_scryfall(self) -> bool:
        """Preuzima svez JSONL sa Scryfall-a i ponovo gradi indeks."""
        try:
            downloader = ScryfallDownloader()

            if not downloader.download_and_extract(self.jsonl_path):
                logger.error("Preuzimanje Scryfall podataka nije uspelo.")
                return False

            if os.path.exists(self.db_path):
                os.remove(self.db_path)

            self._init_db()
            self.load_cards()
            return True
        except Exception as e:
            logger.error("Greška pri ažuriranju SQLite baze: %s", e)
            return False

    # ------------------------------------------------------------------ search

    @staticmethod
    def _fts_query(query: str, prefix: bool) -> str:
        """Korisnicki unos -> FTS izraz; navodnici sprecavaju sintaksne greske."""
        terms = re.findall(r"[^\s\"*()]+", query.lower())
        if not terms:
            return ""
        if prefix:
            return " AND ".join(f'"{t}"*' for t in terms)
        return " AND ".join(f'"{t}"' for t in terms)

    def _has_match(self, table: str, expression: str) -> bool:
        """Samo da li ima pogodaka - bez brojanja svih redova."""
        conn = self._connect()
        try:
            sql = f"SELECT 1 FROM {table} WHERE {table} MATCH ? LIMIT 1"
            return conn.execute(sql, (expression,)).fetchone() is not None
        except sqlite3.OperationalError:
            # Neispravan FTS izraz iz korisnickog unosa - tretiramo kao promasaj.
            return False
        finally:
            conn.close()

    def all_cards(self) -> CardQueryResult:
        return CardQueryResult(self.db_path, order_sql="cards.name_lower, cards.id")

    def search(self, query: str) -> CardQueryResult:
        """Prvo prefiks pretraga (rangirana), pa trigram za delove reci."""
        if not query.strip():
            return self.all_cards()

        prefix_expr = self._fts_query(query, prefix=True)
        if prefix_expr and self._has_match("cards_fts", prefix_expr):
            return CardQueryResult(
                self.db_path,
                where_sql=(
                    "JOIN cards_fts ON cards_fts.rowid = cards.id "
                    "AND cards_fts MATCH ?"
                ),
                params=(prefix_expr,),
                order_sql="bm25(cards_fts), cards.name_lower",
            )

        trigram_expr = self._fts_query(query, prefix=False)
        if trigram_expr:
            return CardQueryResult(
                self.db_path,
                where_sql=(
                    "JOIN cards_trigram ON cards_trigram.rowid = cards.id "
                    "AND cards_trigram MATCH ?"
                ),
                params=(trigram_expr,),
                order_sql="cards.name_lower, cards.id",
            )

        return CardQueryResult(self.db_path, where_sql="WHERE 1 = 0")

    # ------------------------------------------------------------------ lookup

    def _one(self, sql: str, params: tuple) -> Card | None:
        conn = self._connect()
        try:
            row = conn.execute(sql, params).fetchone()
        finally:
            conn.close()

        if not row:
            return None
        try:
            return Card(json.loads(row[0]))
        except ValueError:
            return None

    def find_exact(self, name: str, set_code: str, collector_number: str) -> Card | None:
        return self._one(
            "SELECT raw_json FROM cards "
            "WHERE name_lower = ? AND set_code = ? AND collector_number = ? "
            "ORDER BY id LIMIT 1",
            (name.lower(), str(set_code or "").lower(), str(collector_number or "")),
        )

    def find_cheapest_by_name(self, name: str) -> Card | None:
        """Najjeftinije izdanje; karte bez cene dolaze poslednje."""
        return self._one(
            "SELECT raw_json FROM cards WHERE name_lower = ? "
            "ORDER BY CASE WHEN price_sort > 0 THEN 0 ELSE 1 END, price_sort, id LIMIT 1",
            (name.lower(),),
        )

    def find_by_loose_name(self, name: str) -> Card | None:
        """Uparivanje koje ignorise interpunkciju i razmake."""
        return self._one(
            "SELECT raw_json FROM cards WHERE name_alnum = ? "
            "ORDER BY CASE WHEN price_sort > 0 THEN 0 ELSE 1 END, price_sort, id LIMIT 1",
            (normalize_name(name),),
        )

    def count(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        finally:
            conn.close()
