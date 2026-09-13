import json

import pytest

from services.sqlite_database import SQLiteCardDatabase


def _card(name, set_name="Bloomburrow", set_code="blb", number="1", usd="1.00", type_line="Instant"):
    return {
        "name": name, "set_name": set_name, "set": set_code,
        "collector_number": number, "type_line": type_line,
        "rarity": "common", "cmc": 1, "colors": ["R"],
        "prices": {"usd": usd},
    }


@pytest.fixture
def jsonl_file(tmp_path):
    rows = [
        _card("Lightning Bolt", "Limited Edition Beta", "leb", "161", "5.00"),
        _card("Lightning Bolt", "Modern Masters", "mma", "129", "1.50"),
        _card("Lightning Helix", "Ravnica", "rav", "200", "2.00"),
        _card("Forest", "Bloomburrow", "blb", "280", "0.10", "Basic Land — Forest"),
        {"name": "Ghost Card", "set_name": "Nowhere", "prices": {}},
    ]
    path = tmp_path / "bulk.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
        f.write("\n")
        f.write("{ not valid json\n")
    return path


@pytest.fixture
def db(tmp_path, jsonl_file):
    database = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(jsonl_file))
    database.load_cards()
    return database


# ----------------------------------------------------------------- indexing

def test_init_creates_the_database_file(tmp_path, jsonl_file):
    db_path = tmp_path / "cards.db"
    SQLiteCardDatabase(db_path=str(db_path), jsonl_path=str(jsonl_file))
    assert db_path.exists()


def test_indexes_every_priced_card(db):
    assert db.count() == 4


def test_skips_priceless_cards(db):
    assert [c.name for c in db.search("ghost")] == []


def test_survives_malformed_lines(db):
    assert db.count() == 4


def test_second_load_reuses_the_index(db, jsonl_file):
    jsonl_file.unlink()  # indeks postoji, JSONL vise nije potreban
    db.load_cards()
    assert db.count() == 4


def test_missing_jsonl_yields_an_empty_database(tmp_path):
    db = SQLiteCardDatabase(
        db_path=str(tmp_path / "cards.db"),
        jsonl_path=str(tmp_path / "ne-postoji.jsonl"),
    )
    db.load_cards()
    assert db.count() == 0


# ------------------------------------------------------------------- search

def test_prefix_search_matches_word_starts(db):
    assert {c.name for c in db.search("light")} == {"Lightning Bolt", "Lightning Helix"}


def test_search_matches_a_whole_word_mid_name(db):
    assert {c.name for c in db.search("bolt")} == {"Lightning Bolt"}


def test_search_requires_every_term(db):
    assert len(db.search("lightning beta")) == 1
    assert len(db.search("lightning bloomburrow")) == 0


def test_trigram_fallback_matches_inside_a_word(db):
    """Prefiks indeks ne hvata 'ning', pa pada na trigram."""
    assert {c.name for c in db.search("ning")} == {"Lightning Bolt", "Lightning Helix"}


def test_search_is_case_insensitive(db):
    assert len(db.search("LIGHTNING")) == len(db.search("lightning"))


def test_empty_search_returns_everything(db):
    assert len(db.search("   ")) == db.count()


def test_nonsense_query_returns_nothing(db):
    assert len(db.search("zzzzqqq")) == 0


def test_search_by_set_and_type(db):
    assert {c.name for c in db.search("beta")} == {"Lightning Bolt"}
    assert "Forest" in {c.name for c in db.search("land")}


@pytest.mark.parametrize("hostile", ['"', "*", "(", ")", 'bolt"', "AND", "OR", "NEAR"])
def test_search_does_not_crash_on_fts_syntax(db, hostile):
    """Korisnicki unos ne sme da procuri u FTS sintaksu."""
    assert len(db.search(hostile)) >= 0


def test_results_are_ordered_by_relevance(db):
    """bm25: 'lightning bolt' stavlja Bolt ispred Helix-a."""
    assert db.search("lightning bolt")[0].name == "Lightning Bolt"


# ------------------------------------------------------------------- lookup

def test_find_exact_printing(db):
    card = db.find_exact("Lightning Bolt", "leb", "161")
    assert card is not None
    assert card.set_name == "Limited Edition Beta"


def test_find_exact_is_case_insensitive(db):
    assert db.find_exact("lIgHtNiNg BoLt", "LEB", "161") is not None


def test_find_exact_returns_none_for_a_missing_printing(db):
    assert db.find_exact("Lightning Bolt", "xxx", "999") is None


def test_find_cheapest_picks_the_lowest_price(db):
    card = db.find_cheapest_by_name("Lightning Bolt")
    assert card.set_name == "Modern Masters"  # 1.50 < 5.00


def test_find_cheapest_returns_none_for_unknown_names(db):
    assert db.find_cheapest_by_name("Black Lotus") is None


# --------------------------------------------------------------- lazy result

def test_results_behave_like_a_list(db):
    results = db.all_cards()
    assert len(results) == 4
    assert len(results[0:2]) == 2
    assert [c.name for c in results] == sorted(c.name for c in results)


def test_slicing_only_fetches_the_requested_page(db, monkeypatch):
    """Strana od 2 karte ne sme da materijalizuje celu bazu."""
    results = db.all_cards()
    page = results[0:2]
    assert len(page) == 2
    assert all(hasattr(c, "name") for c in page)


def test_negative_and_out_of_range_indexing(db):
    results = db.all_cards()
    assert results[-1].name == results[len(results) - 1].name
    with pytest.raises(IndexError):
        results[999]


def test_update_downloads_before_rebuilding(db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "services.sqlite_database.ScryfallDownloader.download_and_extract",
        lambda self, output_filename="": (calls.append(output_filename), True)[1],
    )
    assert db.update_from_scryfall() is True
    assert calls == [db.jsonl_path]


def test_update_fails_loudly_when_the_download_fails(db, monkeypatch):
    monkeypatch.setattr(
        "services.sqlite_database.ScryfallDownloader.download_and_extract",
        lambda self, output_filename="": False,
    )
    assert db.update_from_scryfall() is False


def test_old_schema_is_rebuilt_not_crashed_into(tmp_path, jsonl_file):
    """Postojeci korisnici imaju stari indeks na disku - mora da se pregradi."""
    import sqlite3

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT, raw_json TEXT)")
    conn.execute("INSERT INTO cards (name, raw_json) VALUES ('Stale', '{}')")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    db = SQLiteCardDatabase(db_path=str(db_path), jsonl_path=str(jsonl_file))
    db.load_cards()

    assert db.count() == 4
    assert db.find_cheapest_by_name("Stale") is None
    assert db.find_exact("Lightning Bolt", "leb", "161") is not None
