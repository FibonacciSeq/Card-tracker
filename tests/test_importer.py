import pytest

from importer import CardImporter, parse_universal_line


@pytest.mark.parametrize(
    "line,expected",
    [
        ("4 Forest", (4, "Forest", None, None)),
        ("1 Lightning Bolt", (1, "Lightning Bolt", None, None)),
        ("12 Llanowar Elves", (12, "Llanowar Elves", None, None)),
    ],
)
def test_parse_quantity_and_name(line, expected):
    assert parse_universal_line(line) == expected


def test_parse_moxfield_style_line_with_set_and_number():
    assert parse_universal_line("1 Lightning Bolt (LEB) 161") == (1, "Lightning Bolt", "leb", "161")


def test_parse_line_with_set_but_no_collector_number():
    qty, name, set_code, _ = parse_universal_line("2 Forest (BLB)")
    assert (qty, name, set_code) == (2, "Forest", "blb")


def test_bare_name_defaults_to_one_copy():
    assert parse_universal_line("Forest") == (1, "Forest", None, None)


@pytest.mark.parametrize("line", ["", "   ", "// sideboard", "# note"])
def test_comments_and_blanks_are_skipped(line):
    assert parse_universal_line(line) is None


def test_surrounding_whitespace_is_trimmed():
    assert parse_universal_line("  3 Forest  ") == (3, "Forest", None, None)


def test_match_uses_exact_printing_when_set_and_number_given(fake_db):
    db = [c.to_dict() for c in fake_db.cards]
    matched, unmatched = CardImporter.match_cards_with_database([(1, "Lightning Bolt", "leb", "161")], db)

    assert unmatched == []
    assert len(matched) == 1
    assert matched[0]["set"] == "leb"
    assert matched[0]["quantity"] == 1


def test_match_falls_back_to_cheapest_printing_by_name(fake_db):
    db = [c.to_dict() for c in fake_db.cards]
    matched, _ = CardImporter.match_cards_with_database([(2, "Forest", None, None)], db)

    assert len(matched) == 1
    assert matched[0]["name"] == "Forest"
    assert matched[0]["quantity"] == 2


def test_match_is_case_insensitive(fake_db):
    db = [c.to_dict() for c in fake_db.cards]
    matched, _ = CardImporter.match_cards_with_database([(1, "lIgHtNiNg BoLt", None, None)], db)
    assert len(matched) == 1


def test_unknown_cards_are_reported_not_silently_dropped(fake_db):
    """Regresija: neprepoznate karte se nisu prijavljivale korisniku."""
    db = [c.to_dict() for c in fake_db.cards]
    matched, unmatched = CardImporter.match_cards_with_database([(1, "Black Lotus", None, None)], db)

    assert matched == []
    assert unmatched == ["1x Black Lotus"]


def test_parse_card_list_text_end_to_end(fake_db):
    db = [c.to_dict() for c in fake_db.cards]
    matched, unmatched = CardImporter.parse_card_list_text("4 Forest\n// deck\n1 Lightning Bolt (LEB) 161", db)

    assert unmatched == []
    assert [m["name"] for m in matched] == ["Forest", "Lightning Bolt"]
    assert [m["quantity"] for m in matched] == [4, 1]


def test_parse_lines_does_not_touch_the_database():
    """parse_lines je cisto parsiranje - uparivanje ide zasebno."""
    assert CardImporter.parse_lines("4 Forest\n// x\n\n2 Island") == [
        (4, "Forest", None, None),
        (2, "Island", None, None),
    ]
