import pytest

from models.card import Card
from services.card_lookup import InMemoryCardLookup, as_lookup, normalize_name


@pytest.fixture
def cards(bolt_data, forest_data):
    cheap_bolt = dict(bolt_data, set_name="Modern Masters", set="mma",
                      collector_number="129", prices={"usd": "1.50"})
    return [Card(bolt_data), Card(cheap_bolt), Card(forest_data)]


@pytest.fixture
def lookup(cards):
    return InMemoryCardLookup(cards)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jace, the Mind Sculptor", "jacethemindsculptor"),
        ("Fire // Ice", "fireice"),
        ("  Forest  ", "forest"),
        ("Æther Vial", "æthervial"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_find_exact_printing(lookup):
    card = lookup.find_exact("Lightning Bolt", "leb", "161")
    assert card.set_name == "Limited Edition Beta"


def test_find_exact_is_case_insensitive(lookup):
    assert lookup.find_exact("lightning bolt", "LEB", "161") is not None


def test_find_exact_misses_return_none(lookup):
    assert lookup.find_exact("Lightning Bolt", "zzz", "1") is None


def test_find_cheapest_prefers_the_lower_price(lookup):
    assert lookup.find_cheapest_by_name("Lightning Bolt").set_name == "Modern Masters"


def test_find_cheapest_ignores_priceless_printings(bolt_data):
    priced = Card(dict(bolt_data, set_name="Priced", prices={"usd": "3.00"}))
    free = Card(dict(bolt_data, set_name="No Price", prices={}))

    assert InMemoryCardLookup([free, priced]).find_cheapest_by_name("Lightning Bolt").set_name == "Priced"


def test_find_cheapest_returns_none_for_unknown_names(lookup):
    assert lookup.find_cheapest_by_name("Black Lotus") is None


def test_loose_name_ignores_punctuation(bolt_data):
    card = Card(dict(bolt_data, name="Jace, the Mind Sculptor"))
    lookup = InMemoryCardLookup([card])

    assert lookup.find_by_loose_name("Jace the Mind Sculptor") is not None
    assert lookup.find_by_loose_name("jacethemindsculptor") is not None
    assert lookup.find_cheapest_by_name("Jace the Mind Sculptor") is None


def test_as_lookup_accepts_a_plain_list(cards):
    assert as_lookup(cards).find_cheapest_by_name("Forest") is not None


def test_as_lookup_accepts_an_object_with_cards(cards):
    class Db:
        pass

    db = Db()
    db.cards = cards
    assert as_lookup(db).find_cheapest_by_name("Forest") is not None


def test_as_lookup_passes_through_an_existing_lookup(lookup):
    assert as_lookup(lookup) is lookup


def test_as_lookup_accepts_dicts(cards):
    dicts = [c.to_dict() for c in cards]
    assert as_lookup(dicts).find_exact("Forest", "blb", "280") is not None


def test_empty_lookup_finds_nothing():
    empty = InMemoryCardLookup([])
    assert empty.find_cheapest_by_name("Forest") is None
    assert empty.find_exact("Forest", "blb", "280") is None
    assert empty.find_by_loose_name("Forest") is None
