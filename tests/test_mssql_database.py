"""Testovi za SQL Server backend koji ne zahtevaju server.

Mapiranje reda u Card i sastavljanje upita se testiraju nad laznom
konekcijom; testovi koji stvarno gadjaju bazu su u database/tests/.
"""

import pytest

from services.mssql import ConnectionSettings
from services.mssql_database import MssqlCardDatabase, _row_to_card_dict

ROW = (
    "11111111-1111-1111-1111-111111111111",
    "Lightning Bolt", "leb", "Limited Edition Beta", "161",
    "Instant", "common", 1, "R", "https://img/bolt.jpg",
    "5.00", "50.00", "4.50", "45.00",
)


def test_row_maps_to_card_fields():
    data = _row_to_card_dict(ROW)
    assert data["name"] == "Lightning Bolt"
    assert data["set"] == "leb"
    assert data["set_name"] == "Limited Edition Beta"
    assert data["collector_number"] == "161"


def test_row_maps_prices_as_strings():
    prices = _row_to_card_dict(ROW)["prices"]
    assert prices["usd"] == "5.00"
    assert prices["eur_foil"] == "45.00"


def test_null_prices_stay_none():
    row = ROW[:10] + (None, None, None, None)
    assert all(v is None for v in _row_to_card_dict(row)["prices"].values())


def test_colorless_maps_to_empty_list():
    """'C' u bazi znači bezbojna karta; Card očekuje praznu listu."""
    row = ROW[:8] + ("C",) + ROW[9:]
    assert _row_to_card_dict(row)["colors"] == []


def test_multicolour_splits_into_letters():
    row = ROW[:8] + ("WU",) + ROW[9:]
    assert _row_to_card_dict(row)["colors"] == ["W", "U"]


def test_row_builds_a_usable_card(pinned_rates):
    from models.card import Card

    card = Card(_row_to_card_dict(ROW))
    assert card.name == "Lightning Bolt"
    assert card.price_normal_val > 0


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.statements = []

    def execute(self, statement, params=()):
        self.statements.append((statement, params))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    __module__ = "pymssql._pymssql"

    def __init__(self, rows=()):
        self.cursor_obj = FakeCursor(list(rows))

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


@pytest.fixture
def db(monkeypatch):
    database = MssqlCardDatabase(ConnectionSettings(host="x", user="u", password="p"))
    database._fulltext = False          # bez full-text-a -> LIKE grana
    return database


def _capture(monkeypatch, db, rows=None):
    # Podrazumevano jedan red sa nulom: COUNT(*) uvek nesto vrati.
    conn = FakeConn([(0,)] if rows is None else rows)
    monkeypatch.setattr("services.mssql_database.connect", lambda settings: conn)
    return conn


def test_search_without_fulltext_uses_like(monkeypatch, db):
    conn = _capture(monkeypatch, db)
    result = db.search("lightning bolt")
    result._count_rows()

    statement, params = conn.cursor_obj.statements[-1]
    assert "LIKE" in statement
    assert params == ("%lightning%", "%bolt%")


def test_search_requires_every_term(monkeypatch, db):
    conn = _capture(monkeypatch, db)
    db.search("a b c")._count_rows()
    statement, params = conn.cursor_obj.statements[-1]
    assert statement.count("LIKE") == 3
    assert len(params) == 3


def test_search_with_fulltext_uses_contains(monkeypatch, db):
    db._fulltext = True
    conn = _capture(monkeypatch, db)
    db.search("light bolt")._count_rows()

    statement, params = conn.cursor_obj.statements[-1]
    assert "CONTAINS" in statement
    assert params == ('"light*" AND "bolt*"',)


def test_blank_search_returns_everything(monkeypatch, db):
    conn = _capture(monkeypatch, db)
    db.search("   ")._count_rows()
    statement, _ = conn.cursor_obj.statements[-1]
    assert "LIKE" not in statement and "CONTAINS" not in statement


def test_find_exact_lowercases_the_set_code(monkeypatch, db):
    conn = _capture(monkeypatch, db, rows=[ROW])
    db.find_exact("Lightning Bolt", "LEB", "161")
    _, params = conn.cursor_obj.statements[-1]
    assert params == ("Lightning Bolt", "leb", "161")


def test_find_exact_returns_none_when_empty(monkeypatch, db):
    _capture(monkeypatch, db, rows=[])
    assert db.find_exact("X", "y", "1") is None


def test_find_cheapest_orders_priced_cards_first(monkeypatch, db):
    conn = _capture(monkeypatch, db, rows=[ROW])
    db.find_cheapest_by_name("Lightning Bolt")
    statement, _ = conn.cursor_obj.statements[-1]
    assert "PriceEur IS NULL OR PriceEur = 0 THEN 1 ELSE 0" in statement


def test_loose_name_matches_ignoring_punctuation(monkeypatch, db):
    row = ROW[:1] + ("Jace, the Mind Sculptor",) + ROW[2:] + ("Jace, the Mind Sculptor",)
    _capture(monkeypatch, db, rows=[row])
    assert db.find_by_loose_name("Jace the Mind Sculptor") is not None


def test_loose_name_returns_none_when_nothing_matches(monkeypatch, db):
    _capture(monkeypatch, db, rows=[ROW + ("Lightning Bolt",)])
    assert db.find_by_loose_name("Black Lotus") is None


def test_paging_uses_offset_fetch(monkeypatch, db):
    conn = _capture(monkeypatch, db, rows=[])
    db.all_cards()._fetch_json(20, 10)
    statement, params = conn.cursor_obj.statements[-1]
    assert "OFFSET" in statement and "FETCH NEXT" in statement
    assert params[-2:] == (20, 10)
