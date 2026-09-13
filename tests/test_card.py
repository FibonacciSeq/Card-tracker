import pytest

from models.card import Card


def test_basic_fields(bolt_data):
    card = Card(bolt_data)
    assert card.name == "Lightning Bolt"
    assert card.set_name == "Limited Edition Beta"
    assert card.set_code == "leb"
    assert card.collector_number == "161"
    assert card.rarity == "Common"
    assert card.colors == "R"
    assert card.cmc == "1"


def test_colorless_cards_render_as_c(forest_data):
    assert Card(forest_data).colors == "C"


def test_missing_fields_get_placeholders():
    card = Card({})
    assert card.name == "Unknown Name"
    assert card.set_name == "Unknown Set"
    assert card.image_url is None


def test_image_url_falls_back_to_first_card_face():
    card = Card(
        {
            "name": "Delver of Secrets",
            "card_faces": [{"image_uris": {"normal": "https://img.example/front.jpg"}}],
        }
    )
    assert card.image_url == "https://img.example/front.jpg"


def test_integer_cmc_has_no_decimal_point():
    assert Card({"cmc": 3.0}).cmc == "3"
    assert Card({"cmc": 3.5}).cmc == "3.5"


def test_malformed_cmc_defaults_to_zero():
    assert Card({"cmc": "not-a-number"}).cmc_val == 0.0


def test_prices_converted_from_usd(bolt_data):
    card = Card(bolt_data)
    assert card.price_normal == "€4.50"
    assert card.price_foil == "€45.00"
    assert card.price_normal_val == pytest.approx(4.50)


def test_missing_prices_render_as_na():
    card = Card({"name": "Nameless", "prices": {}})
    assert card.price_normal == "N/A"
    assert card.price_foil == "N/A"
    assert card.price_numeric == 0.0


def test_foil_card_reports_the_foil_price(bolt_data):
    normal = Card(bolt_data, is_foil=False)
    foil = Card(bolt_data, is_foil=True)
    assert foil.price_numeric > normal.price_numeric
    assert foil.price_numeric == pytest.approx(45.0)


def test_foil_and_non_foil_are_different_entries(bolt_data):
    """Regresija: foil i non-foil su se ranije spajali u jedan unos."""
    normal = Card(bolt_data, is_foil=False)
    foil = Card(bolt_data, is_foil=True)
    assert normal != foil
    assert hash(normal) != hash(foil)
    assert len({normal, foil}) == 2


def test_same_printing_is_equal(bolt_data):
    assert Card(bolt_data) == Card(dict(bolt_data))
    assert len({Card(bolt_data), Card(dict(bolt_data))}) == 1


def test_different_printings_are_not_equal(bolt_data):
    other = dict(bolt_data, set_name="Revised Edition", collector_number="162")
    assert Card(bolt_data) != Card(other)


def test_card_is_not_equal_to_other_types(bolt_data):
    assert Card(bolt_data) != "Lightning Bolt"
    assert Card(bolt_data) is not None


def test_clone_overrides_foil_flag(bolt_data):
    """Regresija: raw_data['is_foil'] je ranije gazio eksplicitni argument."""
    original = Card(bolt_data, is_foil=False)
    assert original.clone(is_foil=True).is_foil is True
    assert original.clone(is_foil=True).clone(is_foil=False).is_foil is False


def test_clone_keeps_foil_by_default(bolt_data):
    foil = Card(bolt_data, is_foil=True)
    assert foil.clone().is_foil is True


def test_clone_sets_quantity(bolt_data):
    assert Card(bolt_data).clone(quantity=4).quantity == 4


def test_clone_does_not_mutate_the_original(bolt_data):
    original = Card(bolt_data, is_foil=False)
    original.clone(is_foil=True, quantity=9)
    assert original.is_foil is False
    assert original.quantity == 1


def test_search_matches_all_terms(bolt_data):
    card = Card(bolt_data)
    assert card.matches_query(["lightning"])
    assert card.matches_query(["lightning", "beta"])
    assert card.matches_query(["lightning", "instant", "161"])
    assert not card.matches_query(["lightning", "unstable"])


def test_sorting_is_alphabetical(bolt_data, forest_data):
    cards = sorted([Card(bolt_data), Card(forest_data)])
    assert [c.name for c in cards] == ["Forest", "Lightning Bolt"]


def test_colored_cards_sort_before_colorless(bolt_data, forest_data):
    assert Card(bolt_data).color_sort_key < Card(forest_data).color_sort_key


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"prices": {"usd": "1.00"}}, True),
        ({"prices": {"eur": "1.00"}}, True),
        ({"prices": {}, "layout": "token"}, True),
        ({"prices": {}}, False),
        ({}, False),
    ],
)
def test_has_valid_price(data, expected):
    assert Card.has_valid_price(data) is expected


def test_to_dict_roundtrips(bolt_data):
    card = Card(bolt_data, is_foil=True, quantity=3)
    rebuilt = Card(card.to_dict())
    assert rebuilt.name == card.name
    assert rebuilt.set_code == card.set_code
    assert rebuilt.is_foil is True
    assert rebuilt.quantity == 3
    assert rebuilt == card
