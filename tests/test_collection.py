import json

import pytest

from models.card import Card
from services.card_collection import CardCollection


def test_new_collection_is_empty():
    col = CardCollection()
    assert col.items == []
    assert col.get_total_count() == 0
    assert col.get_total_value_eur() == 0.0


def test_adding_the_same_card_twice_bumps_quantity(bolt_data):
    col = CardCollection()
    col.add_card(Card(bolt_data))
    col.add_card(Card(bolt_data))
    assert len(col.items) == 1
    assert col.items[0].quantity == 2
    assert col.get_total_count() == 2


def test_foil_and_non_foil_stay_separate(bolt_data):
    """Regresija: dodavanje foila je ranije samo uvecavalo non-foil unos."""
    col = CardCollection()
    col.add_card(Card(bolt_data, is_foil=False))
    col.add_card(Card(bolt_data, is_foil=True))

    assert len(col.items) == 2
    assert col.get_normal_count() == 1
    assert col.get_foil_count() == 1
    assert col.get_unique_count() == 1  # i dalje je ista kartica po imenu


def test_remove_decrements_before_deleting(bolt_data):
    col = CardCollection()
    col.add_card(Card(bolt_data).clone(quantity=2))

    col.remove_card(Card(bolt_data))
    assert col.items[0].quantity == 1

    col.remove_card(Card(bolt_data))
    assert col.items == []


def test_removing_a_foil_leaves_the_non_foil_alone(bolt_data):
    col = CardCollection()
    col.add_card(Card(bolt_data, is_foil=False))
    col.add_card(Card(bolt_data, is_foil=True))

    col.remove_card(Card(bolt_data, is_foil=True))

    assert len(col.items) == 1
    assert col.items[0].is_foil is False


def test_removing_a_missing_card_is_a_no_op(bolt_data, forest_data):
    col = CardCollection()
    col.add_card(Card(bolt_data))
    col.remove_card(Card(forest_data))
    assert len(col.items) == 1


def test_items_stay_sorted(bolt_data, forest_data):
    col = CardCollection()
    col.add_card(Card(bolt_data))
    col.add_card(Card(forest_data))
    assert [c.name for c in col.items] == ["Forest", "Lightning Bolt"]


def test_totals_account_for_quantity(bolt_data):
    col = CardCollection()
    col.add_card(Card(bolt_data).clone(quantity=3))

    assert col.get_total_count() == 3
    assert col.get_total_value_eur() == pytest.approx(13.50)  # 3 x 4.50
    assert col.get_total_value() == pytest.approx(13.50)
    assert col.get_total_value_rsd() > 0


def test_foil_total_uses_foil_price(bolt_data):
    col = CardCollection()
    col.add_card(Card(bolt_data, is_foil=True))
    assert col.get_total_value_eur() == pytest.approx(45.00)


def test_save_returns_success_and_path(tmp_path, bolt_data):
    """Regresija: argumenti su bili zamenjeni pa je save() uvek pucao."""
    target = tmp_path / "kolekcija.json"
    col = CardCollection(str(target))
    col.add_card(Card(bolt_data))

    ok, name = col.save()

    assert ok is True
    assert name == str(target)
    assert target.exists()


def test_saved_file_has_the_expected_shape(tmp_path, bolt_data):
    target = tmp_path / "kolekcija.json"
    col = CardCollection(str(target))
    col.add_card(Card(bolt_data, is_foil=True).clone(is_foil=True, quantity=2))
    col.save()

    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["name"] == "Lightning Bolt"
    assert data[0]["set"] == "leb"
    assert data[0]["quantity"] == 2
    assert data[0]["is_foil"] is True


def test_save_does_not_leave_a_temp_file_behind(tmp_path, bolt_data):
    target = tmp_path / "kolekcija.json"
    col = CardCollection(str(target))
    col.add_card(Card(bolt_data))
    col.save()
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_failure_is_reported_not_raised(tmp_path, bolt_data):
    col = CardCollection(str(tmp_path / "nema" / "ovog" / "foldera.json"))
    col.add_card(Card(bolt_data))
    ok, _ = col.save()
    assert ok is False


def test_save_load_roundtrip(tmp_path, fake_db, bolt_data, forest_data):
    target = tmp_path / "kolekcija.json"

    original = CardCollection(str(target))
    original.add_card(Card(bolt_data, is_foil=True).clone(is_foil=True, quantity=2))
    original.add_card(Card(forest_data).clone(quantity=4))
    original.save()

    restored = CardCollection(str(target))
    restored.load(fake_db)

    assert restored.get_total_count() == 6
    assert restored.get_foil_count() == 2
    assert restored.get_normal_count() == 4
    assert [c.name for c in restored.items] == ["Forest", "Lightning Bolt"]


def test_loading_a_missing_file_yields_an_empty_collection(tmp_path, fake_db):
    col = CardCollection(str(tmp_path / "ne-postoji.json"))
    assert col.load(fake_db) == []


def test_import_from_text(fake_db):
    col = CardCollection()
    added, unmatched = col.import_from_text("4 Forest\n2 Lightning Bolt", fake_db)

    assert added == 2
    assert unmatched == []
    assert col.get_total_count() == 6


def test_import_ignores_comments_and_blank_lines(fake_db):
    col = CardCollection()
    added, _ = col.import_from_text("// deck\n\n4 Forest\n# note", fake_db)
    assert added == 1
    assert col.get_total_count() == 4


def test_import_of_empty_text_adds_nothing(fake_db):
    col = CardCollection()
    assert col.import_from_text("", fake_db) == (0, [])


def test_excel_collection_load_uses_quantity_not_duplicate_rows(tmp_path, fake_db):
    """Regresija: ucitavanje je dodavalo istu referencu qty puta sa quantity=1."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv kartice", "Set iz kog je kartica", "Kolekcijski broj kartice", "Kolicina"])
    ws.append(["Forest", "blb", "280", 4])
    path = tmp_path / "col.xlsx"
    wb.save(path)

    col = CardCollection(str(path))
    col.load(fake_db)

    assert len(col.items) == 1
    assert col.items[0].quantity == 4
    assert col.get_total_count() == 4


def test_excel_collection_load_does_not_alias_entries(tmp_path, fake_db):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv kartice", "Kolicina"])
    ws.append(["Forest", 2])
    ws.append(["Lightning Bolt", 1])
    path = tmp_path / "col.xlsx"
    wb.save(path)

    col = CardCollection(str(path))
    col.load(fake_db)

    assert len({id(item) for item in col.items}) == len(col.items)


def test_import_reports_cards_it_could_not_find(fake_db):
    """Regresija: uvoz iz teksta je tiho odbacivao neprepoznate kartice."""
    col = CardCollection()
    added, unmatched = col.import_from_text("4 Forest\n2 Black Lotus\n1 Mox Pearl", fake_db)

    assert added == 1
    assert unmatched == ["2x Black Lotus", "1x Mox Pearl"]
    assert col.get_total_count() == 4
