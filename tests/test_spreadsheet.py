from services.spreadsheet import cell, detect_columns


def test_detects_a_simple_header():
    rows = [("Naziv", "Kolicina"), ("Forest", 4)]
    start, cols = detect_columns(rows)
    assert start == 1
    assert cols["name"] == 0
    assert cols["quantity"] == 1


def test_leading_blank_column_does_not_shift_indices():
    """Regresija: filtriranje praznih celija je pomeralo numeraciju kolona."""
    rows = [(None, "Naziv", "Kolicina"), (None, "Forest", 4)]
    start, cols = detect_columns(rows)
    assert cols["name"] == 1
    assert cols["quantity"] == 2
    assert cell(rows[start], cols, "name") == "Forest"


def test_header_below_a_title_row():
    rows = [("Lista zaliha", None), ("Naziv", "Kolicina"), ("Forest", 4)]
    start, cols = detect_columns(rows)
    assert start == 2
    assert cell(rows[start], cols, "name") == "Forest"


def test_first_matching_column_wins():
    """'Card Name' i 'Card #' oba sadrže 'card'."""
    rows = [("Card Name", "Card #"), ("Forest", "280")]
    _, cols = detect_columns(rows)
    assert cols["name"] == 0


def test_recognises_the_richer_stock_columns():
    rows = [
        ("Naziv", "Set", "Collector", "Kolicina", "Foil", "Stanje", "Lokacija", "Nabavna"),
        ("Forest", "blb", "280", 4, "Da", "NM", "BOX1", "20"),
    ]
    _, cols = detect_columns(rows)
    for field in ("name", "set_code", "collector_number", "quantity",
                  "is_foil", "condition", "location", "unit_cost"):
        assert field in cols, field


def test_falls_back_to_first_two_columns():
    rows = [("Forest", 4), ("Island", 2)]
    start, cols = detect_columns(rows)
    assert start == 0
    assert cols == {"name": 0, "quantity": 1}


def test_cell_returns_none_for_missing_or_empty():
    rows = [("Naziv", "Kolicina"), ("Forest", None)]
    _, cols = detect_columns(rows)
    assert cell(rows[1], cols, "quantity") is None
    assert cell(rows[1], cols, "location") is None


def test_cell_trims_whitespace():
    rows = [("Naziv",), ("  Forest  ",)]
    _, cols = detect_columns(rows)
    assert cell(rows[1], cols, "name") == "Forest"


def test_blank_only_cell_is_none():
    rows = [("Naziv",), ("   ",)]
    _, cols = detect_columns(rows)
    assert cell(rows[1], cols, "name") is None


def test_empty_input_is_harmless():
    start, cols = detect_columns([])
    assert start == 0
    assert cols["name"] == 0
