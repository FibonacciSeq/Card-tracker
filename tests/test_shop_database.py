"""Testovi za lokalnu bazu prodavnice (zalihe + porudzbine)."""

import sqlite3
from contextlib import closing

import pytest

from models.card import Card
from services.shop_database import SHOP_SCHEMA_VERSION, MarketItem, ShopDatabase, suggested_price_rsd


@pytest.fixture
def shop(tmp_path):
    return ShopDatabase(str(tmp_path / "shop.db"))


@pytest.fixture
def bolt(bolt_data):
    return Card(bolt_data)


@pytest.fixture
def stock_id(shop, bolt):
    return shop.add_stock(bolt, quantity=3)


# ------------------------------------------------------------------- schema


def test_schema_version_is_recorded(shop):
    with closing(sqlite3.connect(shop.db_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SHOP_SCHEMA_VERSION


def test_opening_a_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="novijom"):
        ShopDatabase(str(path))


# ------------------------------------------------------------------ stock


def test_add_stock_creates_an_available_item(shop, bolt):
    shop.add_stock(bolt, quantity=3)

    items = shop.list_stock()
    assert len(items) == 1
    item = items[0]
    assert item.name == "Lightning Bolt"
    assert item.quantity == 3
    assert item.reserved == 0
    assert item.available == 3
    assert item.unit_price_rsd == suggested_price_rsd(bolt, False)


def test_same_sku_increments_quantity(shop, bolt):
    shop.add_stock(bolt, quantity=2)
    shop.add_stock(bolt, quantity=5)

    items = shop.list_stock()
    assert len(items) == 1
    assert items[0].quantity == 7


def test_foil_and_condition_are_separate_skus(shop, bolt):
    shop.add_stock(bolt, quantity=1)
    shop.add_stock(bolt, is_foil=True, quantity=1)
    shop.add_stock(bolt, condition_code="LP", quantity=1)

    assert len(shop.list_stock()) == 3


def test_condition_lowers_the_suggested_price(shop, bolt):
    shop.add_stock(bolt, condition_code="LP", quantity=1)
    item = shop.list_stock()[0]
    assert item.unit_price_rsd == suggested_price_rsd(bolt, False, "LP")
    assert item.unit_price_rsd < suggested_price_rsd(bolt, False, "NM")


def test_only_available_filter_hides_empty_and_reserved_rows(shop, bolt):
    empty = shop.add_stock(bolt)
    shop.set_stock(empty, quantity=0)

    shop.add_stock(bolt, is_foil=True, quantity=1)
    foil = next(item for item in shop.list_stock() if item.is_foil)
    foil_id = foil.stock_id

    shop.create_order("Kupac", "k@example.com", "", "", [(foil_id, 1)])

    assert {item.stock_id for item in shop.list_stock(only_available=True)} == set()


def test_search_matches_name_set_and_number(shop, bolt):
    shop.add_stock(bolt, quantity=1)
    assert len(shop.list_stock("lightning")) == 1
    assert len(shop.list_stock("beta")) == 1
    assert len(shop.list_stock("161")) == 1
    assert len(shop.list_stock("forest")) == 0


def test_find_stock_for_card_only_matches_the_same_sku(shop, bolt):
    normal = shop.find_stock_for_card(bolt, is_foil=False, condition_code="NM")
    assert normal is None

    shop.add_stock(bolt, is_foil=False, condition_code="NM", quantity=2)
    shop.add_stock(bolt, is_foil=True, condition_code="NM", quantity=1)

    normal = shop.find_stock_for_card(bolt, is_foil=False, condition_code="NM")
    foil = shop.find_stock_for_card(bolt, is_foil=True, condition_code="NM")

    assert normal is not None and normal.quantity == 2
    assert foil is not None and foil.quantity == 1
    assert shop.find_stock_for_card(bolt, is_foil=False, condition_code="LP") is None


def test_set_stock_cannot_go_below_reserved(shop, stock_id):
    shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 2)])

    with pytest.raises(ValueError, match="rezervisano"):
        shop.set_stock(stock_id, quantity=1)

    shop.set_stock(stock_id, quantity=2)
    assert shop.get_stock(stock_id).available == 0


def test_remove_stock_is_blocked_while_reserved(shop, stock_id):
    shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="rezervisan"):
        shop.remove_stock(stock_id)

    order_id = shop.list_orders()[0].order_id
    shop.update_order_status(order_id, "CANCELLED")

    shop.remove_stock(stock_id)
    assert shop.list_stock() == []


# ----------------------------------------------------------------- orders


def test_create_order_reserves_stock_and_sums_total(shop, stock_id):
    item = shop.get_stock(stock_id)
    order_id = shop.create_order("Marko Marković", "marko@example.com", "", "Beograd", [(stock_id, 2)])

    order = shop.get_order(order_id)
    assert order.customer_name == "Marko Marković"
    assert order.email == "marko@example.com"
    assert order.note == "Beograd"
    assert order.status == "NEW"
    assert order.total_rsd == 2 * item.unit_price_rsd

    assert shop.get_stock(stock_id).reserved == 2
    assert shop.get_stock(stock_id).available == 1


def test_order_lines_snapshot_the_price(shop, stock_id):
    order_id = shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 1)])
    original = shop.get_order(order_id).total_rsd

    shop.set_stock(stock_id, unit_price_rsd=999999)

    line = shop.get_order_lines(order_id)[0]
    assert line.unit_price_rsd != 999999
    assert shop.get_order(order_id).total_rsd == original


def test_order_can_exceed_available_stock_as_a_backorder(shop, stock_id):
    price = shop.get_stock(stock_id).unit_price_rsd
    order_id = shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 4)])

    item = shop.get_stock(stock_id)
    assert shop.get_order(order_id).total_rsd == 4 * price
    assert item.reserved == 4
    assert item.available == 0
    assert item.backordered == 1


def test_customer_can_order_a_completely_out_of_stock_card(shop, bolt):
    empty_id = shop.add_stock(bolt)
    shop.set_stock(empty_id, quantity=0)
    price = shop.get_stock(empty_id).unit_price_rsd

    order_id = shop.create_order("Kupac", "", "0601234567", "", [(empty_id, 2)])

    item = shop.get_stock(empty_id)
    assert shop.get_order(order_id).total_rsd == 2 * price
    assert item.quantity == 0
    assert item.reserved == 2
    assert item.available == 0
    assert item.backordered == 2

    with pytest.raises(ValueError, match="Nema dovoljno"):
        shop.update_order_status(order_id, "DELIVERED")

    shop.add_stock(bolt, quantity=2)
    shop.update_order_status(order_id, "DELIVERED")
    assert shop.get_stock(empty_id).quantity == 0


def test_market_order_creates_a_zero_stock_sku_and_orders_backorder(shop, bolt):
    item = MarketItem.from_card(bolt, unit_price_rsd=750)

    order_id = shop.create_market_order("Kupac", "k@example.com", "", "", [(item, 2)])

    stock = shop.find_stock_for_card(bolt)
    assert stock is not None
    assert stock.quantity == 0
    assert stock.reserved == 2
    assert stock.available == 0
    assert stock.backordered == 2
    assert stock.unit_price_rsd == 750

    line = shop.get_order_lines(order_id)[0]
    assert line.stock_id == stock.stock_id
    assert line.quantity == 2
    assert line.unit_price_rsd == 750
    assert shop.get_order(order_id).total_rsd == 1500

    shop.add_stock(bolt, quantity=2, unit_price_rsd=750)
    shop.update_order_status(order_id, "DELIVERED")
    delivered = shop.get_stock(stock.stock_id)
    assert delivered is not None
    assert delivered.quantity == 0


def test_order_line_missing_quantity_tracks_current_stock(shop, bolt):
    item = MarketItem.from_card(bolt, unit_price_rsd=500)
    order_id = shop.create_market_order("Kupac", "k@example.com", "", "", [(item, 2)])

    line = shop.get_order_lines(order_id)[0]
    assert line.stock_quantity == 0
    assert line.missing_quantity == 2

    shop.add_stock(bolt, quantity=1, unit_price_rsd=500)
    line = shop.get_order_lines(order_id)[0]
    assert line.stock_quantity == 1
    assert line.missing_quantity == 1

    shop.add_stock(bolt, quantity=1, unit_price_rsd=500)
    line = shop.get_order_lines(order_id)[0]
    assert line.stock_quantity == 2
    assert line.missing_quantity == 0


def test_market_order_uses_the_existing_owner_price(shop, bolt):
    shop.add_stock(bolt, quantity=1, unit_price_rsd=700)
    item = MarketItem.from_card(bolt, unit_price_rsd=999)

    order_id = shop.create_market_order("Kupac", "k@example.com", "", "", [(item, 2)])

    line = shop.get_order_lines(order_id)[0]
    assert line.unit_price_rsd == 700
    assert shop.get_order(order_id).total_rsd == 1400
    stock = shop.find_stock_for_card(bolt)
    assert stock is not None
    assert stock.reserved == 2


def test_market_order_merges_duplicate_variants(shop, bolt):
    item = MarketItem.from_card(bolt, unit_price_rsd=500)

    order_id = shop.create_market_order(
        "Kupac",
        "k@example.com",
        "",
        "",
        [(item, 1), (item, 2)],
    )

    lines = shop.get_order_lines(order_id)
    assert len(lines) == 1
    assert lines[0].quantity == 3
    assert shop.get_order(order_id).total_rsd == 1500


def test_out_of_stock_backorder_can_still_be_price_edited(shop, bolt):
    empty_id = shop.add_stock(bolt)
    shop.set_stock(empty_id, quantity=0)
    shop.create_order("Kupac", "", "0601234567", "", [(empty_id, 2)])

    shop.set_stock(empty_id, quantity=0, unit_price_rsd=555)

    item = shop.get_stock(empty_id)
    assert item.quantity == 0
    assert item.unit_price_rsd == 555
    assert item.backordered == 2


def test_backordered_orders_wait_for_enough_stock(shop, stock_id, bolt):
    first = shop.create_order("Prvi", "", "0601111111", "", [(stock_id, 2)])
    second = shop.create_order("Drugi", "", "0602222222", "", [(stock_id, 2)])

    assert shop.get_stock(stock_id).reserved == 4
    assert shop.get_stock(stock_id).backordered == 1

    shop.update_order_status(first, "DELIVERED")
    with pytest.raises(ValueError, match="Nema dovoljno"):
        shop.update_order_status(second, "DELIVERED")

    shop.add_stock(bolt, quantity=1)
    shop.update_order_status(second, "DELIVERED")
    assert shop.get_stock(stock_id).quantity == 0
    assert shop.get_stock(stock_id).reserved == 0


def test_contact_is_required(shop, stock_id):
    with pytest.raises(ValueError, match="Ime"):
        shop.create_order("", "k@example.com", "", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="e-mail ili telefon"):
        shop.create_order("Kupac", "", "", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="E-mail"):
        shop.create_order("Kupac", "nije-adresa", "", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="E-mail"):
        shop.create_order("Kupac", "k@localhost", "", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="Telefon"):
        shop.create_order("Kupac", "", "telefon", "", [(stock_id, 1)])


def test_contact_and_note_lengths_are_bounded(shop, stock_id):
    with pytest.raises(ValueError, match="200"):
        shop.create_order("x" * 201, "k@example.com", "", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="254"):
        shop.create_order("Kupac", "a" * 245 + "@example.com", "", "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="50"):
        shop.create_order("Kupac", "", "1" * 51, "", [(stock_id, 1)])

    with pytest.raises(ValueError, match="2000"):
        shop.create_order("Kupac", "k@example.com", "", "x" * 2001, [(stock_id, 1)])


def test_contact_details_are_trimmed(shop, stock_id):
    order_id = shop.create_order(
        "  Kupac  ",
        "  k@example.com  ",
        "  0601234567  ",
        "  Napomena  ",
        [(stock_id, 1)],
    )

    order = shop.get_order(order_id)
    assert order.customer_name == "Kupac"
    assert order.email == "k@example.com"
    assert order.phone == "0601234567"
    assert order.note == "Napomena"


def test_empty_order_is_rejected(shop):
    with pytest.raises(ValueError, match="nema nijednu"):
        shop.create_order("Kupac", "k@example.com", "", "", [])


def test_status_flow_deducts_stock_only_on_delivery(shop, stock_id):
    order_id = shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 2)])

    shop.update_order_status(order_id, "ORDERED")
    assert shop.get_order(order_id).status == "ORDERED"
    assert shop.get_stock(stock_id).quantity == 3

    shop.update_order_status(order_id, "FULFILLED")
    assert shop.get_order(order_id).status == "FULFILLED"
    assert shop.get_stock(stock_id).quantity == 3

    shop.update_order_status(order_id, "DELIVERED")
    order = shop.get_order(order_id)
    assert order.status == "DELIVERED"
    assert order.delivered_at
    assert shop.get_stock(stock_id).quantity == 1
    assert shop.get_stock(stock_id).reserved == 0


def test_cancelling_releases_the_reservation(shop, stock_id):
    order_id = shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 2)])

    shop.update_order_status(order_id, "CANCELLED")

    assert shop.get_stock(stock_id).reserved == 0
    assert shop.get_stock(stock_id).available == 3


def test_cannot_move_backwards_or_past_delivery(shop, stock_id):
    order_id = shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 1)])
    shop.update_order_status(order_id, "FULFILLED")

    with pytest.raises(ValueError, match="ne moze preci"):
        shop.update_order_status(order_id, "ORDERED")

    shop.update_order_status(order_id, "DELIVERED")
    with pytest.raises(ValueError, match="ne moze preci"):
        shop.update_order_status(order_id, "CANCELLED")


def test_list_orders_can_be_filtered_by_status(shop, stock_id):
    first = shop.create_order("Prvi", "", "0601111111", "", [(stock_id, 1)])
    shop.create_order("Drugi", "", "0602222222", "", [(stock_id, 1)])
    shop.update_order_status(first, "ORDERED")

    assert len(shop.list_orders()) == 2
    assert [order.order_id for order in shop.list_orders("NEW")] == [first + 1]
    assert [order.order_id for order in shop.list_orders("ORDERED")] == [first]


def test_stats_count_stock_and_orders(shop, stock_id):
    shop.create_order("Kupac", "", "0601234567", "", [(stock_id, 2)])

    stock = shop.stock_stats()
    orders = shop.order_stats()

    assert stock["units"] == 3
    assert stock["reserved"] == 2
    assert stock["backordered"] == 0
    assert stock["available"] == 1
    assert orders["total"] == 1
    assert orders["new"] == 1
    assert orders["open"] == 1
    assert orders["revenue_rsd"] == 0
