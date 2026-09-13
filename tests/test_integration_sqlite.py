"""End-to-end: kolekcija i uvoz rade direktno nad SQLite bazom.

Ranije su ove putanje gradile mape nad celom bazom u memoriji; sada idu
kroz CardLookup, pa ovi testovi cuvaju taj ugovor.
"""

import json

import openpyxl
import pytest

from services.card_collection import CardCollection
from services.excel_importer import ExcelImporter
from services.sqlite_database import SQLiteCardDatabase


def _card(name, set_name, set_code, number, usd):
    return {
        "name": name, "set_name": set_name, "set": set_code,
        "collector_number": number, "type_line": "Instant",
        "rarity": "rare", "cmc": 1, "colors": ["R"],
        "prices": {"usd": usd, "usd_foil": str(float(usd) * 10)},
    }


@pytest.fixture
def db(tmp_path):
    rows = [
        _card("Lightning Bolt", "Limited Edition Beta", "leb", "161", "5.00"),
        _card("Lightning Bolt", "Modern Masters", "mma", "129", "1.50"),
        _card("Forest", "Bloomburrow", "blb", "280", "0.10"),
    ]
    jsonl = tmp_path / "bulk.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    database = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(jsonl))
    database.load_cards()
    return database


def test_import_from_text_against_sqlite(db):
    col = CardCollection()
    added, unmatched = col.import_from_text("4 Forest\n2 Lightning Bolt (LEB) 161", db)

    assert (added, unmatched) == (2, [])
    assert col.get_total_count() == 6
    assert {c.set_name for c in col.items} == {"Bloomburrow", "Limited Edition Beta"}


def test_import_without_a_set_picks_the_cheapest_printing(db):
    col = CardCollection()
    col.import_from_text("1 Lightning Bolt", db)
    assert col.items[0].set_name == "Modern Masters"  # 1.50 < 5.00


def test_import_reports_unknown_cards_against_sqlite(db):
    col = CardCollection()
    added, unmatched = col.import_from_text("1 Black Lotus\n2 Forest", db)

    assert added == 1
    assert unmatched == ["1x Black Lotus"]


def test_json_save_load_roundtrip_against_sqlite(tmp_path, db):
    target = tmp_path / "kolekcija.json"

    original = CardCollection(str(target))
    original.import_from_text("2 Lightning Bolt (LEB) 161\n4 Forest", db)
    assert original.save()[0] is True

    restored = CardCollection(str(target))
    restored.load(db)

    assert restored.get_total_count() == 6
    assert [c.name for c in restored.items] == ["Forest", "Lightning Bolt"]
    assert restored.items[1].set_name == "Limited Edition Beta"


def test_foil_survives_a_roundtrip_against_sqlite(tmp_path, db):
    target = tmp_path / "kolekcija.json"

    original = CardCollection(str(target))
    bolt = db.find_exact("Lightning Bolt", "leb", "161")
    original.add_card(bolt.clone(is_foil=True, quantity=3))
    original.save()

    restored = CardCollection(str(target))
    restored.load(db)

    assert restored.get_foil_count() == 3
    assert restored.get_normal_count() == 0


def test_excel_import_against_sqlite(tmp_path, db):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv", "Kolicina"])
    ws.append(["Forest", 4])
    ws.append(["Black Lotus", 1])
    path = tmp_path / "in.xlsx"
    wb.save(path)

    col = CardCollection()
    added, unmatched = ExcelImporter.import_file(str(path), db, col)

    assert added == 4
    assert unmatched == ["1x Black Lotus"]


def test_collection_load_does_not_materialise_the_database(db, monkeypatch):
    """Kolekcija se ucitava kroz lookup, ne kroz prolaz kroz sve karte."""

    def explode(self):
        raise AssertionError("nesto i dalje cita celu bazu u memoriju")

    monkeypatch.setattr(SQLiteCardDatabase, "all_cards", explode)

    col = CardCollection()
    added, _ = col.import_from_text("1 Forest", db)
    assert added == 1
