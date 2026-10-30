"""Targeted tests for branches that are hard to reach through normal flows.

These are intentionally small and behaviour-focused: each one exercises a
real fallback, validation, cleanup, or platform path that the happy-path suite
does not cover.
"""

import builtins
import json
import os
import sqlite3
import threading
import types
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import openpyxl
import pytest
from PIL import Image

import downloader as downloader_module
from collection import CollectionStorage
from importer import parse_card_list_text
from models.card import Card
from services import mssql
from services.card_collection import CardCollection
from services.card_lookup import InMemoryCardLookup
from services.image_loader import ImageLoader
from services.mssql import ConnectionSettings, connection
from services.mssql_database import MssqlCardDatabase
from services.pricing import DEFAULT_RATES, PricingService
from services.shop_database import (
    MarketItem,
    OrderLine,
    OrderSummary,
    ShopDatabase,
    StockItem,
    card_key,
    condition_label,
    market_key,
    suggested_price_rsd,
)
from services.sqlite_database import SQLiteCardDatabase

# ----------------------------------------------------------------- collection


def test_collection_save_removes_temp_file_after_failure(tmp_path, monkeypatch):
    target = tmp_path / "collection.json"

    def fail_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("collection.os.replace", fail_replace)
    ok, _ = CollectionStorage.save_to_file([{"name": "Forest"}], str(target))

    assert ok is False
    assert not Path(str(target) + ".tmp").exists()


def test_collection_load_falls_back_to_xlsx_extension(tmp_path, fake_db, forest_data):
    target = tmp_path / "collection"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv", "Kolicina"])
    ws.append(["Forest", 2])
    wb.save(str(target) + ".xlsx")

    loaded = CollectionStorage.load_from_file(str(target), fake_db)
    assert len(loaded) == 1
    assert loaded[0].quantity == 2


def test_collection_load_falls_back_to_json_extension(tmp_path, fake_db, forest_data):
    target = tmp_path / "collection"
    Path(str(target) + ".json").write_text(
        json.dumps([{"name": "Forest", "set": "blb", "collector_number": "280", "quantity": 3}]),
        encoding="utf-8",
    )

    loaded = CollectionStorage.load_from_file(str(target), fake_db)
    assert len(loaded) == 1
    assert loaded[0].quantity == 3


def test_collection_json_loader_supports_plain_dicts(tmp_path, forest_data):
    target = tmp_path / "collection.json"
    target.write_text(
        json.dumps([{"name": "Forest", "set": "blb", "collector_number": "280", "quantity": 2, "is_foil": True}]),
        encoding="utf-8",
    )

    loaded = CollectionStorage._load_from_json(str(target), [forest_data])
    assert loaded == [
        {**forest_data, "quantity": 2, "is_foil": True},
    ]


def test_collection_json_loader_returns_empty_on_bad_json(tmp_path, fake_db):
    target = tmp_path / "collection.json"
    target.write_text("{not json", encoding="utf-8")
    assert CollectionStorage._load_from_json(str(target), fake_db) == []


def test_collection_excel_loader_returns_empty_for_bad_file(tmp_path, fake_db):
    assert CollectionStorage._load_from_excel(str(tmp_path / "missing.xlsx"), fake_db) == []


def test_collection_excel_loader_handles_an_empty_sheet(tmp_path, fake_db):
    target = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(target)
    assert CollectionStorage._load_from_excel(str(target), fake_db) == []


def test_collection_excel_loader_requires_a_name_column(tmp_path, fake_db):
    target = tmp_path / "no-name.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Kolicina"])
    ws.append([2])
    wb.save(target)

    assert CollectionStorage._load_from_excel(str(target), fake_db) == []


def test_collection_excel_loader_skips_blank_rows_and_bad_quantities(tmp_path, fake_db):
    target = tmp_path / "rows.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv", "Kolicina"])
    ws.append([None, 1])
    ws.append(["   ", 1])
    ws.append(["Forest", "not-a-number"])
    ws.append(["Forest", 2])
    wb.save(target)

    loaded = CollectionStorage._load_from_excel(str(target), fake_db)
    assert len(loaded) == 2
    assert [item.quantity for item in loaded] == [1, 2]


def test_collection_with_quantity_handles_dicts():
    original = {"name": "Forest"}
    result = CollectionStorage._with_quantity(original, 4, is_foil=True)
    assert result == {"name": "Forest", "quantity": 4, "is_foil": True}
    assert original == {"name": "Forest"}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    path = tmp_path / "cache"
    monkeypatch.setattr(ImageLoader, "_cache_dir", str(path))
    ImageLoader._ensure_cache_dir()
    return path


@pytest.fixture
def downloader(tmp_path):
    return downloader_module.ScryfallDownloader(temp_file=str(tmp_path / "temp.jsonl.gz"))


def test_card_collection_adds_a_card_without_quantity(bolt_data):
    card = Card(bolt_data)
    del card.quantity
    collection = CardCollection()
    collection.add_card(card)
    assert collection.items[0].quantity == 1


# ----------------------------------------------------------------- downloader


def test_downloader_cleanup_ignores_a_missing_temp_file(tmp_path):
    downloader_ = downloader_module.ScryfallDownloader(temp_file=str(tmp_path / "missing.gz"))
    downloader_._cleanup_temp_file()


def test_downloader_cleanup_logs_os_errors(tmp_path, monkeypatch):
    target = tmp_path / "temp.gz"
    target.write_bytes(b"x")
    downloader_ = downloader_module.ScryfallDownloader(temp_file=str(target))

    def fail_remove(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("downloader.os.remove", fail_remove)
    downloader_._cleanup_temp_file()


class _StreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_stream_download_skips_empty_chunks(tmp_path, monkeypatch):
    target = tmp_path / "temp.gz"
    downloader_ = downloader_module.ScryfallDownloader(temp_file=str(target))
    monkeypatch.setattr(
        "downloader.requests.get",
        lambda *a, **k: _StreamResponse([b"", b"payload"]),
    )

    downloader_._stream_download("https://data.example/cards.gz")
    assert target.read_bytes() == b"payload"


def test_decompress_failure_without_partial_file(downloader, tmp_path, monkeypatch):
    output = tmp_path / "cards.jsonl"
    monkeypatch.setattr("downloader.gzip.open", lambda *a, **k: (_ for _ in ()).throw(OSError("bad gzip")))

    with pytest.raises(OSError):
        downloader._decompress(str(output))

    assert not (tmp_path / "cards.jsonl.part").exists()


def test_wrapper_delegates_to_the_downloader(monkeypatch):
    monkeypatch.setattr(
        downloader_module.ScryfallDownloader,
        "download_and_extract",
        lambda self, output_filename="": output_filename == "target.jsonl",
    )
    assert downloader_module.download_and_extract_scryfall("target.jsonl") is True


# ---------------------------------------------------------------------- Card


def test_card_handles_invalid_usd_prices():
    card = Card({"prices": {"usd": "not-a-number", "usd_foil": "also-bad"}})
    assert card.price_normal == "N/A"
    assert card.price_foil == "N/A"
    assert card.price_normal_rsd == 0
    assert card.price_foil_rsd == 0


def test_card_uses_eur_prices_when_usd_is_absent():
    card = Card({"prices": {"eur": "2.50", "eur_foil": "3.50"}})
    assert card.price_normal == "€2.50"
    assert card.price_foil == "€3.50"
    assert card.price_normal_rsd > 0
    assert card.price_foil_rsd > 0


def test_card_handles_invalid_eur_prices():
    card = Card({"prices": {"eur": "bad", "eur_foil": "bad"}})
    assert card.price_normal == "N/A"
    assert card.price_foil == "N/A"


def test_card_ignores_malformed_card_faces():
    card = Card({"card_faces": ["not-a-dict"]})
    assert card.image_url is None


def test_card_multicolour_sort_key():
    assert Card({"colors": ["R", "U"]}).color_sort_key == (2, "RU")


# ------------------------------------------------------------------- pricing


class _FakeRateResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _reset_rates(monkeypatch, *, cache=None, last_fetch=None, last_attempt=None):
    monkeypatch.setattr(PricingService, "_rates_cache", dict(cache or {}))
    monkeypatch.setattr(PricingService, "_last_fetch_date", last_fetch)
    monkeypatch.setattr(PricingService, "_last_attempt", last_attempt)


def test_pricing_refreshes_rates_on_success(monkeypatch):
    _reset_rates(monkeypatch)
    monkeypatch.setattr(
        "services.pricing.requests.get",
        lambda *a, **k: _FakeRateResponse(payload={"rates": {"EUR": 1.1, "RSD": 120.0}}),
    )

    PricingService.update_exchange_rates()

    assert PricingService._rates_cache == {"EUR": 1.1, "RSD": 120.0}
    assert PricingService._last_fetch_date == datetime.now().date()


def test_pricing_falls_back_to_defaults_on_non_200(monkeypatch):
    _reset_rates(monkeypatch)
    monkeypatch.setattr("services.pricing.requests.get", lambda *a, **k: _FakeRateResponse(status_code=500))

    PricingService.update_exchange_rates()

    assert PricingService._rates_cache == DEFAULT_RATES


def test_pricing_falls_back_to_defaults_on_exception(monkeypatch):
    _reset_rates(monkeypatch)

    def boom(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr("services.pricing.requests.get", boom)
    PricingService.update_exchange_rates()

    assert PricingService._rates_cache == DEFAULT_RATES


def test_pricing_respects_the_retry_window(monkeypatch):
    _reset_rates(monkeypatch, last_attempt=datetime.now())
    monkeypatch.setattr(
        "services.pricing.requests.get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must not be called")),
    )

    PricingService.update_exchange_rates()
    assert PricingService._rates_cache == {}


def test_pricing_eur_to_rsd_handles_a_zero_eur_rate(monkeypatch):
    _reset_rates(monkeypatch, cache={"EUR": 0.0, "RSD": 100.0}, last_fetch=datetime.now().date())
    assert PricingService.eur_to_rsd_rate() == DEFAULT_RATES["RSD"]


# --------------------------------------------------------------------- MSSQL


def test_forced_driver_is_used(monkeypatch):
    monkeypatch.setenv("CARDTRACKER_MSSQL_DRIVER", "pymssql")
    assert mssql._available_driver() == "pymssql"


def _import_hook(available):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("pyodbc", "pymssql") and name not in available:
            raise ImportError(name)
        if name in ("pyodbc", "pymssql") and name in available:
            return types.SimpleNamespace(name=name)
        return real_import(name, *args, **kwargs)

    return fake_import


def test_driver_discovery_prefers_pyodbc(monkeypatch):
    monkeypatch.delenv("CARDTRACKER_MSSQL_DRIVER", raising=False)
    monkeypatch.setattr(builtins, "__import__", _import_hook({"pyodbc"}))
    assert mssql._available_driver() == "pyodbc"


def test_driver_discovery_falls_back_to_pymssql(monkeypatch):
    monkeypatch.delenv("CARDTRACKER_MSSQL_DRIVER", raising=False)
    monkeypatch.setattr(builtins, "__import__", _import_hook({"pymssql"}))
    assert mssql._available_driver() == "pymssql"


def test_driver_discovery_reports_missing_drivers(monkeypatch):
    monkeypatch.delenv("CARDTRACKER_MSSQL_DRIVER", raising=False)
    monkeypatch.setattr(builtins, "__import__", _import_hook(set()))
    with pytest.raises(RuntimeError, match="drajver"):
        mssql._available_driver()


def test_connect_uses_pyodbc(monkeypatch):
    calls = []

    def connect(conn_str: str) -> str:
        calls.append(conn_str)
        return "connection"

    fake_pyodbc = types.SimpleNamespace(connect=connect)
    monkeypatch.setenv("CARDTRACKER_MSSQL_DRIVER", "pyodbc")
    monkeypatch.setitem(__import__("sys").modules, "pyodbc", fake_pyodbc)

    result = mssql.connect(ConnectionSettings(host="db", user="u", password="p"))
    assert result == "connection"
    assert "SERVER=db,1433" in calls[0]


def test_connect_uses_pymssql(monkeypatch):
    captured = {}
    fake_pymssql = types.SimpleNamespace(
        connect=lambda **kwargs: captured.update(kwargs) or "connection",
    )
    monkeypatch.setenv("CARDTRACKER_MSSQL_DRIVER", "pymssql")
    monkeypatch.setitem(__import__("sys").modules, "pymssql", fake_pymssql)

    assert mssql.connect(ConnectionSettings(host="db", user="u", password="p")) == "connection"
    assert captured["server"] == "db"
    assert captured["database"] == "CardTracker"


def test_pymssql_rejects_windows_authentication(monkeypatch):
    fake_pymssql = types.SimpleNamespace(connect=lambda **kwargs: "connection")
    monkeypatch.setenv("CARDTRACKER_MSSQL_DRIVER", "pymssql")
    monkeypatch.setitem(__import__("sys").modules, "pymssql", fake_pymssql)

    with pytest.raises(RuntimeError, match="Windows"):
        mssql.connect(ConnectionSettings(trusted=True))


class _FakeConnection:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_connection_commits_and_closes(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr("services.mssql.connect", lambda settings: conn)

    with connection() as opened:
        assert opened is conn

    assert conn.committed and conn.closed
    assert not conn.rolled_back


def test_connection_rolls_back_on_error(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr("services.mssql.connect", lambda settings: conn)

    with pytest.raises(RuntimeError), connection():
        raise RuntimeError("boom")

    assert conn.rolled_back and conn.closed


def test_odbc_string_disables_encryption_and_trust():
    string = ConnectionSettings(encrypt=False, trust_server_certificate=False).odbc_connection_string()
    assert "Encrypt=no" in string
    assert "TrustServerCertificate=no" in string


def test_mssql_fulltext_property_all_branches(monkeypatch):
    db = MssqlCardDatabase(ConnectionSettings())
    monkeypatch.setattr(db, "_query", lambda *a, **k: [(1, 1)])
    assert db.fulltext_available is True

    db = MssqlCardDatabase(ConnectionSettings())
    monkeypatch.setattr(db, "_query", lambda *a, **k: [(0, 0)])
    assert db.fulltext_available is False

    db = MssqlCardDatabase(ConnectionSettings())
    monkeypatch.setattr(db, "_query", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    assert db.fulltext_available is False


def test_mssql_count_and_load_cards(monkeypatch):
    db = MssqlCardDatabase(ConnectionSettings())
    monkeypatch.setattr(db, "_query", lambda *a, **k: [(3,)])
    db.load_cards()


# -------------------------------------------------------------------- SQLite


def test_sqlite_price_sort_uses_eur_and_handles_bad_values():
    assert SQLiteCardDatabase._price_sort({"prices": {"eur": "2.00"}}) == 2.0
    assert SQLiteCardDatabase._price_sort({"prices": {"usd": "bad"}}) == 0.0
    assert SQLiteCardDatabase._price_sort({"prices": {"eur": "bad"}}) == 0.0


def test_sqlite_import_flushes_a_full_batch(tmp_path, monkeypatch):
    jsonl = tmp_path / "cards.jsonl"
    rows = [
        {"name": "Forest", "set": "blb", "collector_number": "1", "prices": {"usd": "1.00"}},
        {"name": "Island", "set": "blb", "collector_number": "2", "prices": {"usd": "1.00"}},
    ]
    jsonl.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(SQLiteCardDatabase, "BATCH_SIZE", 1)

    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(jsonl))
    db.load_cards()
    assert db.count() == 2


def test_sqlite_update_reports_rebuild_errors(tmp_path, monkeypatch):
    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(tmp_path / "cards.jsonl"))
    monkeypatch.setattr(
        "services.sqlite_database.ScryfallDownloader.download_and_extract",
        lambda self, output_filename="": True,
    )
    monkeypatch.setattr(db, "_init_db", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert db.update_from_scryfall() is False


def test_sqlite_has_match_treats_fts_errors_as_no_match(tmp_path):
    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(tmp_path / "missing.jsonl"))
    assert db._has_match("cards_fts", '"') is False


def test_sqlite_one_ignores_corrupt_raw_json(tmp_path):
    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(tmp_path / "missing.jsonl"))
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO cards (name, name_lower, raw_json) VALUES ('X', 'x', 'not-json')",
        )
        conn.commit()
    assert db._one("SELECT raw_json FROM cards WHERE name = 'X'", ()) is None


def test_sqlite_search_with_only_hostile_characters_returns_empty(tmp_path):
    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(tmp_path / "missing.jsonl"))
    assert list(db.search("()")) == []


# --------------------------------------------------------------- image loader


def test_cache_path_uses_a_default_name(cache_dir):
    assert os.path.basename(ImageLoader._cache_path("https://cards.example/")) == "image.jpg"


def test_download_removes_a_pre_created_partial_file(cache_dir, monkeypatch):
    target = cache_dir / "card.jpg"
    (cache_dir / "card.jpg.part").write_bytes(b"partial")

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr("services.image_loader.urllib.request.urlopen", boom)
    with pytest.raises(OSError):
        ImageLoader._download("https://cards.example/card.jpg", str(target))
    assert not (cache_dir / "card.jpg.part").exists()


def test_trim_cache_logs_listdir_errors(cache_dir, monkeypatch):
    monkeypatch.setattr("services.image_loader.os.listdir", lambda _path: (_ for _ in ()).throw(OSError("no")))
    ImageLoader._trim_cache()


def test_make_photo_image_propagates_unexpected_errors(monkeypatch):
    class BrokenImageTk:
        @staticmethod
        def PhotoImage(_image):
            raise RuntimeError("tk broken")

    monkeypatch.setattr("services.image_loader.import_module", lambda _name: BrokenImageTk)
    with pytest.raises(RuntimeError):
        ImageLoader._make_photo_image(Image.new("RGB", (2, 2)))


def test_load_card_image_reports_photo_creation_errors(cache_dir, monkeypatch):
    image_path = cache_dir / "card.png"
    Image.new("RGB", (4, 4)).save(image_path)
    monkeypatch.setattr(
        ImageLoader,
        "_make_photo_image",
        staticmethod(lambda _image: (_ for _ in ()).throw(RuntimeError("no tk"))),
    )

    done = threading.Event()
    errors = []

    def on_error(exc):
        errors.append(exc)
        done.set()

    ImageLoader.load_card_image(
        "https://cards.example/card.png",
        callback=lambda *a: None,
        on_error=on_error,
        schedule=lambda _delay, func: func(),
    )

    assert done.wait(timeout=5)
    assert isinstance(errors[0], RuntimeError)


def test_load_card_image_without_callback_still_decodes(cache_dir, monkeypatch):
    image_path = cache_dir / "card.png"
    Image.new("RGB", (4, 4)).save(image_path)

    class InlineThread:
        def __init__(self, target, daemon=True):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr("services.image_loader.threading.Thread", InlineThread)
    ImageLoader.load_card_image("https://cards.example/card.png", callback=None, schedule=lambda _d, f: f())


# --------------------------------------------------------------------- Excel


def test_exporter_reports_errors(tmp_path, monkeypatch):
    class BrokenWorkbook:
        def __init__(self):
            raise RuntimeError("cannot create workbook")

    monkeypatch.setattr("services.excel_exporter.openpyxl.Workbook", BrokenWorkbook)
    from services.excel_exporter import CollectionExporter

    ok, message = CollectionExporter.export_to_excel([], str(tmp_path / "x.xlsx"))
    assert ok is False
    assert "cannot create workbook" in message


@pytest.mark.parametrize(
    "row,expected_added",
    [
        (["UKUPNO", 5], 0),
        (["Forest", "bad"], 1),
        (["Forest", 0], 0),
    ],
)
def test_importer_skips_totals_bad_quantities_and_zero_rows(tmp_path, fake_db, row, expected_added):
    from services.excel_importer import ExcelImporter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv", "Kolicina"])
    ws.append(row)
    path = tmp_path / "input.xlsx"
    wb.save(path)

    collection = CardCollection()
    added, _ = ExcelImporter.import_file(str(path), fake_db, collection)
    assert added == expected_added


def test_spreadsheet_skips_empty_rows_and_blank_cells():
    from services.spreadsheet import detect_columns

    rows = [(), ("   ",), ("Naziv", "Kolicina")]
    start, columns = detect_columns(rows)
    assert start == 3
    assert columns["name"] == 0


# ---------------------------------------------------------------- card lookup


def test_card_lookup_handles_unparseable_prices():
    cards = [
        {"name": "Forest", "price_numeric": "not-a-number"},
        {"name": "Forest", "price_numeric": "3"},
    ]
    lookup = InMemoryCardLookup(cards)
    assert lookup.find_cheapest_by_name("Forest") is cards[1]
    assert lookup.all_cards() == cards


# -------------------------------------------------------------------- importer


def test_parse_card_list_text_wrapper(fake_db):
    matched, unmatched = parse_card_list_text("1 Forest", fake_db)
    assert unmatched == []
    assert matched[0].name == "Forest"


# --------------------------------------------------------------- shop database


@pytest.fixture
def shop(tmp_path):
    return ShopDatabase(str(tmp_path / "shop.db"))


@pytest.fixture
def bolt(bolt_data):
    return Card(bolt_data)


@pytest.fixture
def stock_id(shop, bolt):
    return shop.add_stock(bolt, quantity=3)


def _stock_item(**overrides: Any) -> StockItem:
    values: dict[str, Any] = {
        "stock_id": 1,
        "card_key": "key",
        "name": "Forest",
        "set_code": "blb",
        "set_name": "Bloomburrow",
        "collector_number": "280",
        "rarity": "common",
        "type_line": "Land",
        "is_foil": False,
        "condition_code": "NM",
        "language_code": "en",
        "quantity": 3,
        "reserved": 4,
        "unit_price_rsd": 100,
        "image_url": "",
    }
    values.update(overrides)
    return StockItem(**values)


def _market_item(**overrides: Any) -> MarketItem:
    values: dict[str, Any] = {
        "card_key": "key",
        "name": "Forest",
        "set_code": "blb",
        "set_name": "Bloomburrow",
        "collector_number": "280",
        "rarity": "common",
        "type_line": "Land",
        "is_foil": False,
        "condition_code": "NM",
        "language_code": "en",
        "unit_price_rsd": 100,
        "quantity": 0,
        "reserved": 2,
        "image_url": "",
        "stock_id": None,
    }
    values.update(overrides)
    return MarketItem(**values)


def test_shop_price_and_key_edges(bolt):
    assert suggested_price_rsd(bolt, False, "UNKNOWN") == suggested_price_rsd(bolt, False, "NM")
    assert suggested_price_rsd(Card({"prices": {}}), False) == 0
    assert card_key(Card({**bolt.raw_data, "id": "abc"})) == "abc"
    assert market_key(bolt, True, "LP", "sr")[1:] == (True, "LP", "sr")
    assert condition_label("UNKNOWN") == "UNKNOWN - UNKNOWN"


def test_stock_and_market_item_properties():
    stock = _stock_item(condition_code="UNKNOWN", set_code="", is_foil=True)
    assert stock.available == 0
    assert stock.backordered == 1
    assert stock.condition_name == "UNKNOWN"
    assert stock.foil_label == "Foil"
    assert stock.set_label == "Bloomburrow"

    market = _market_item(set_code="", is_foil=True)
    assert market.available == 0
    assert market.backordered == 2
    assert market.foil_label == "Foil"
    assert market.set_label == "Bloomburrow"
    assert MarketItem.from_stock(stock).card_key == "key"


def test_market_item_from_card_uses_suggested_price(bolt):
    item = MarketItem.from_card(bolt)
    assert item.unit_price_rsd == suggested_price_rsd(bolt, False, "NM")


def test_order_value_objects():
    summary = OrderSummary(
        order_id=1,
        customer_name="X",
        email="",
        phone="",
        note="",
        status="NEW",
        total_rsd=100,
        created_at="",
        updated_at="",
        delivered_at="",
    )
    assert summary.status_text == "Nova"
    line = OrderLine(
        line_id=1,
        order_id=1,
        stock_id=None,
        name="Forest",
        set_code="",
        set_name="",
        collector_number="",
        is_foil=True,
        condition_code="NM",
        quantity=2,
        unit_price_rsd=50,
    )
    assert line.subtotal_rsd == 100
    assert line.missing_quantity == 2
    assert line.foil_label == "Foil"


def test_shop_stock_validation(shop, bolt):
    assert shop.get_stock(999) is None
    with pytest.raises(ValueError, match="stanje"):
        shop.add_stock(bolt, condition_code="XX")
    with pytest.raises(ValueError, match="Kolicina"):
        shop.add_stock(bolt, quantity=0)
    with pytest.raises(ValueError, match="Cena"):
        shop.add_stock(bolt, unit_price_rsd=-1)


def test_shop_set_and_remove_missing_rows(shop, stock_id):
    with pytest.raises(ValueError, match="ne postoji"):
        shop.set_stock(999, quantity=1)
    with pytest.raises(ValueError, match="Kolicina"):
        shop.set_stock(stock_id, quantity=-1)
    with pytest.raises(ValueError, match="Cena"):
        shop.set_stock(stock_id, unit_price_rsd=-1)
    with pytest.raises(ValueError, match="ne postoji"):
        shop.remove_stock(999)


def test_create_order_validation_edges(shop, stock_id):
    with pytest.raises(ValueError, match="Kolicina"):
        shop.create_order("Kupac", "k@example.com", "", "", [(stock_id, 0)])
    with pytest.raises(ValueError, match="vise nije"):
        shop.create_order("Kupac", "k@example.com", "", "", [(999, 1)])


def test_create_market_order_validation_edges(shop, bolt):
    item = MarketItem.from_card(bolt)
    with pytest.raises(ValueError, match="2000"):
        shop.create_market_order("Kupac", "k@example.com", "", "x" * 2001, [(item, 1)])
    with pytest.raises(ValueError, match="Kolicina"):
        shop.create_market_order("Kupac", "k@example.com", "", "", [(item, 0)])
    with pytest.raises(ValueError, match="stanje"):
        shop.create_market_order(
            "Kupac",
            "k@example.com",
            "",
            "",
            [(MarketItem(**{**item.__dict__, "condition_code": "XX"}), 1)],
        )
    with pytest.raises(ValueError, match="nema nijednu"):
        shop.create_market_order("Kupac", "k@example.com", "", "", [])


def test_ensure_stock_row_rejects_bad_items(shop):
    class FakeCursor:
        lastrowid = 1

        def fetchone(self):
            return None

    class FakeConn:
        def execute(self, *_args, **_kwargs):
            return FakeCursor()

    with pytest.raises(ValueError, match="stanje"):
        ShopDatabase._ensure_stock_row(cast(sqlite3.Connection, FakeConn()), _market_item(condition_code="XX"))
    with pytest.raises(ValueError, match="Cena"):
        ShopDatabase._ensure_stock_row(cast(sqlite3.Connection, FakeConn()), _market_item(unit_price_rsd=-1))


def test_ensure_stock_row_reports_missing_insert_id(shop):
    class FakeCursor:
        lastrowid = None

        def fetchone(self):
            return None

    class FakeConn:
        def execute(self, *_args, **_kwargs):
            return FakeCursor()

    with pytest.raises(RuntimeError, match="nije sacuvana"):
        ShopDatabase._ensure_stock_row(cast(sqlite3.Connection, FakeConn()), _market_item())


def test_ensure_stock_row_reports_missing_reloaded_row(shop):
    class FakeCursor:
        lastrowid = 1

        def fetchone(self):
            return None

    class FakeConn:
        def execute(self, _statement, *_args, **_kwargs):
            return FakeCursor()

    with pytest.raises(RuntimeError, match="nije sacuvana"):
        ShopDatabase._ensure_stock_row(cast(sqlite3.Connection, FakeConn()), _market_item())


def test_allowed_statuses_and_status_validation(shop, stock_id):
    order_id = shop.create_order("Kupac", "k@example.com", "", "", [(stock_id, 1)])
    assert "CANCELLED" in shop.allowed_statuses(order_id)
    assert shop.allowed_statuses(999) == set()

    with pytest.raises(ValueError, match="Nepoznat status"):
        shop.update_order_status(order_id, "BOGUS")
    with pytest.raises(ValueError, match="ne postoji"):
        shop.update_order_status(999, "ORDERED")

    shop.update_order_status(order_id, "NEW")
    assert shop.get_order(order_id).status == "NEW"


def test_delivery_rejects_a_line_without_a_stock_row(shop, stock_id):
    order_id = shop.create_order("Kupac", "k@example.com", "", "", [(stock_id, 1)])
    with shop._transaction() as conn:
        conn.execute("UPDATE shop_order_line SET stock_id = NULL WHERE order_id = ?", (order_id,))

    with pytest.raises(ValueError, match="vise nema stavku"):
        shop.update_order_status(order_id, "DELIVERED")


def test_sqlite_and_import_helpers_are_not_dead_code():
    """Small guard that the coverage-only imports remain real public helpers."""
    assert sqlite3.OperationalError is not None
    assert DEFAULT_RATES


# ------------------------------------------------------- remaining branch edges


def test_collection_json_skips_an_unmatched_entry(tmp_path, forest_data):
    target = tmp_path / "collection.json"
    target.write_text(
        json.dumps(
            [
                {"name": "Missing", "set": "xxx", "collector_number": "1"},
                {"name": "Forest", "set": "blb", "collector_number": "280", "quantity": 2},
            ]
        ),
        encoding="utf-8",
    )
    loaded = CollectionStorage._load_from_json(str(target), [forest_data])
    assert len(loaded) == 1
    assert loaded[0]["name"] == "Forest"


def test_collection_excel_handles_missing_quantity_column_and_unmatched_rows(tmp_path, fake_db):
    target = tmp_path / "collection.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Naziv"])
    ws.append(["Missing Card"])
    ws.append(["Forest"])
    wb.save(target)

    loaded = CollectionStorage._load_from_excel(str(target), fake_db)
    assert len(loaded) == 1
    assert loaded[0].quantity == 1


def test_card_lookup_keeps_the_existing_cheapest_when_a_price_is_zero():
    cards = [
        {"name": "Forest", "price_numeric": "5"},
        {"name": "Forest", "price_numeric": "0"},
    ]
    lookup = InMemoryCardLookup(cards)
    assert lookup.find_cheapest_by_name("Forest") is cards[0]


def test_card_query_handles_empty_limits_bad_rows_and_slices(tmp_path):
    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(tmp_path / "missing.jsonl"))
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO cards (name, name_lower, raw_json) VALUES ('Forest', 'forest', ?)",
            (json.dumps({"name": "Forest"}),),
        )
        conn.execute(
            "INSERT INTO cards (name, name_lower, raw_json) VALUES ('Bad', 'bad', 'not-json')",
        )
        conn.commit()

    query = db.all_cards()
    assert query._fetch(0, 0) == []
    assert [card.name for card in query._fetch(0, 2)] == ["Forest"]

    with db._connect() as conn:
        conn.execute("DELETE FROM cards WHERE name = 'Bad'")
        conn.commit()
    query = db.all_cards()
    assert [card.name for card in query[::2]] == ["Forest"]


def test_image_loader_trims_cache_after_a_download(cache_dir, monkeypatch):
    monkeypatch.setattr(
        ImageLoader,
        "_download",
        staticmethod(lambda _url, path: Image.new("RGB", (2, 2)).save(path)),
    )
    trimmed = []
    monkeypatch.setattr(ImageLoader, "_trim_cache", staticmethod(lambda: trimmed.append(True)))
    monkeypatch.setattr(ImageLoader, "_make_photo_image", staticmethod(lambda _image: "photo"))

    done = threading.Event()
    ImageLoader.load_card_image(
        "https://cards.example/card.png",
        callback=lambda *a: done.set(),
        schedule=lambda _delay, func: func(),
    )
    assert done.wait(timeout=5)
    assert trimmed == [True]


def test_image_loader_error_without_on_error_callback(cache_dir, monkeypatch):
    monkeypatch.setattr(
        ImageLoader,
        "_download",
        staticmethod(lambda _url, _path: (_ for _ in ()).throw(OSError("offline"))),
    )
    ImageLoader.load_card_image(
        "https://cards.example/card.png",
        callback=lambda *a: None,
        schedule=lambda _delay, func: func(),
    )


def test_image_loader_photo_error_without_on_error_callback(cache_dir, monkeypatch):
    target = cache_dir / "card.png"
    Image.new("RGB", (2, 2)).save(target)
    monkeypatch.setattr(
        ImageLoader,
        "_make_photo_image",
        staticmethod(lambda _image: (_ for _ in ()).throw(RuntimeError("no tk"))),
    )
    ImageLoader.load_card_image(
        "https://cards.example/card.png",
        callback=lambda *a: None,
        schedule=lambda _delay, func: func(),
    )


def test_shop_memory_database_skips_filesystem_setup():
    db = ShopDatabase(":memory:")
    assert db.db_path == ":memory:"


def test_shop_database_without_a_parent_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("services.shop_database.os.path.dirname", lambda _path: "")
    db = ShopDatabase("shop.db")
    assert db.db_path == "shop.db"


def test_get_stock_scans_past_non_matching_rows(shop, stock_id):
    assert shop.get_stock(999) is None
    assert shop.get_stock(stock_id).stock_id == stock_id


def test_sqlite_price_sort_without_any_price():
    assert SQLiteCardDatabase._price_sort({"prices": {}}) == 0.0


def test_sqlite_update_handles_a_missing_database_file(tmp_path, monkeypatch):
    db = SQLiteCardDatabase(db_path=str(tmp_path / "cards.db"), jsonl_path=str(tmp_path / "missing.jsonl"))
    os.remove(db.db_path)
    monkeypatch.setattr(
        "services.sqlite_database.ScryfallDownloader.download_and_extract",
        lambda self, output_filename="": True,
    )
    assert db.update_from_scryfall() is True
