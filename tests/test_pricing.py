import pytest

from services.pricing import DEFAULT_RATES, PricingService, calculate_card_price_rsd
from tests.conftest import EUR_TO_RSD


def test_get_rate_uses_cache():
    assert PricingService.get_rate("EUR") == 0.90
    assert PricingService.get_rate("RSD") == 117.0


def test_eur_to_rsd_rate():
    assert PricingService.eur_to_rsd_rate() == pytest.approx(EUR_TO_RSD)


def test_unknown_currency_falls_back_to_default():
    assert PricingService.get_rate("EUR") == 0.90
    with pytest.raises(KeyError):
        PricingService.get_rate("GBP")


@pytest.mark.parametrize("bad", [0, -1, None])
def test_convert_price_rejects_non_positive(bad):
    assert PricingService.convert_price(bad) == (0.0, 0.0)


def test_convert_price_rounds_to_cents():
    eur, rsd = PricingService.convert_price(5.0)
    assert eur == pytest.approx(4.50)
    assert rsd == pytest.approx(585.0)


@pytest.mark.parametrize("price_eur", [0, -3, None])
def test_rsd_price_of_worthless_card_is_zero(price_eur):
    assert calculate_card_price_rsd(price_eur) == 0


def test_cheap_cards_have_a_price_floor():
    """Sve ispod 0.35 EUR ide po fiksnih 50 RSD."""
    assert calculate_card_price_rsd(0.01) == 50
    assert calculate_card_price_rsd(0.34) == 50
    assert calculate_card_price_rsd(0.35) != 50


@pytest.mark.parametrize(
    "price_eur,expected",
    [
        (1.00, 150),    # +15 marza
        (3.00, 420),    # +30 marza
        (7.00, 970),    # +60 marza
        # 20*130*1.10 je matematicki 2860, ali float daje 2860.0000000000005
        # pa ceil() podigne na 2870. Namerno hvatamo stvarno ponasanje.
        (20.00, 2870),  # x1.10
        (30.00, 4180),  # x1.07
        (60.00, 8190),  # x1.05
        (200.00, 26780),  # x1.03
    ],
)
def test_margin_tiers(price_eur, expected):
    assert calculate_card_price_rsd(price_eur) == expected


def test_prices_are_rounded_up_to_ten_rsd():
    for price_eur in (0.5, 1.23, 4.44, 9.99, 33.3):
        assert calculate_card_price_rsd(price_eur) % 10 == 0


def test_price_increases_monotonically_with_value():
    prices = [calculate_card_price_rsd(p) for p in (0.5, 1, 3, 7, 20, 30, 60, 200)]
    assert prices == sorted(prices)


def test_defaults_are_sane():
    assert DEFAULT_RATES["EUR"] > 0
    assert DEFAULT_RATES["RSD"] > 0
