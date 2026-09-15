"""Testovi za mapiranje ulaznih podataka u staging - bez SQL Servera."""

import csv

import openpyxl
import pytest

from tools.etl_scryfall import _image_url, _staging_row
from tools.etl_stock import read_rows, rows_to_staging

# ----------------------------------------------------------------- scryfall

def test_staging_row_extracts_the_expected_fields(bolt_data):
    data = dict(bolt_data, id="11111111-1111-1111-1111-111111111111")
    row = _staging_row(data)

    assert row[0] == "11111111-1111-1111-1111-111111111111"
    assert row[1] == "Lightning Bolt"
    assert row[2] == "leb"
    assert row[4] == "161"


def test_staging_row_keeps_prices_as_text():
    """Cene ostaju tekst; konverziju radi baza preko TRY_CONVERT."""
    row = _staging_row({"name": "X", "prices": {"usd": "5.00", "eur": "4.50"}})
    assert "5.00" in row
    assert "4.50" in row


def test_colorless_cards_are_marked_c():
    assert _staging_row({"name": "Sol Ring", "colors": []})[8] == "C"


def test_missing_prices_become_none():
    row = _staging_row({"name": "X", "prices": {}})
    assert row[11] is None and row[13] is None


def test_image_url_from_card_faces():
    data = {"card_faces": [{"image_uris": {"normal": "https://img/front.jpg"}}]}
    assert _image_url(data) == "https://img/front.jpg"


def test_image_url_absent():
    assert _image_url({"name": "X"}) is None


# -------------------------------------------------------------------- stock

def _xlsx(tmp_path, rows, name="in.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    path = tmp_path / name
    wb.save(path)
    return str(path)


def test_reads_xlsx(tmp_path):
    path = _xlsx(tmp_path, [("Naziv", "Kolicina"), ("Forest", 4)])
    assert read_rows(path)[1][0] == "Forest"


def test_reads_csv(tmp_path):
    path = tmp_path / "in.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["Naziv", "Kolicina"], ["Forest", "4"]])
    assert read_rows(str(path))[1][0] == "Forest"


def test_unsupported_format_is_rejected(tmp_path):
    path = tmp_path / "in.txt"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Nepodržan"):
        read_rows(str(path))


def test_rows_to_staging_maps_all_columns():
    rows = [
        ("Naziv", "Set", "Collector", "Kolicina", "Foil", "Stanje", "Lokacija", "Nabavna"),
        ("Forest", "blb", "280", 4, "Da", "NM", "BOX1", "20"),
    ]
    staged = rows_to_staging(rows)

    assert len(staged) == 1
    row_no, name, set_code, collector, qty, foil, cond, lang, loc, cost = staged[0]
    assert (name, set_code, collector, qty) == ("Forest", "blb", "280", "4")
    assert (foil, cond, loc, cost) == ("Da", "NM", "BOX1", "20")
    assert row_no == 2


def test_rows_to_staging_skips_rows_without_a_name():
    rows = [("Naziv", "Kolicina"), (None, 5), ("Forest", 4), ("   ", 9)]
    assert [r[1] for r in rows_to_staging(rows)] == ["Forest"]


def test_rows_to_staging_handles_a_leading_blank_column():
    rows = [(None, "Naziv", "Kolicina"), (None, "Forest", 4)]
    staged = rows_to_staging(rows)
    assert staged[0][1] == "Forest"
    assert staged[0][4] == "4"


def test_rows_to_staging_records_source_row_numbers():
    """Broj reda ide u etl.LoadError, da se greška nađe u originalnoj tabeli."""
    rows = [("Naslov", None), ("Naziv", "Kolicina"), ("Forest", 4), ("Island", 2)]
    assert [r[0] for r in rows_to_staging(rows)] == [3, 4]


def test_missing_optional_columns_become_none():
    staged = rows_to_staging([("Naziv", "Kolicina"), ("Forest", 4)])
    _, _, set_code, collector, _, foil, cond, lang, loc, cost = staged[0]
    assert set_code is None and collector is None and foil is None
    assert cond is None and lang is None and loc is None and cost is None


def test_empty_sheet_yields_nothing():
    assert rows_to_staging([]) == []
