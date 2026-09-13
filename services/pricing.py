import logging
import math
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

DEFAULT_RATES = {"EUR": 0.92, "RSD": 117.0}

# Koliko dugo cekamo pre ponovnog pokusaja ako preuzimanje kurseva padne.
# Bez ovoga bi svaka konstrukcija Card objekta pokusala novi HTTP poziv.
RETRY_AFTER = timedelta(minutes=10)


class PricingService:
    _rates_cache = {}
    _last_fetch_date = None
    _last_attempt = None

    @classmethod
    def update_exchange_rates(cls):
        today = datetime.now().date()

        if cls._rates_cache and cls._last_fetch_date == today:
            return

        now = datetime.now()
        if cls._last_attempt is not None and now - cls._last_attempt < RETRY_AFTER:
            # Skoro smo pokusali i nije uspelo - koristimo ono sto imamo.
            return

        cls._last_attempt = now

        try:
            url = "https://open.er-api.com/v6/latest/USD"
            headers = {"User-Agent": "MyMTGApp/1.0"}
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                rates = data.get("rates", {})

                cls._rates_cache = {
                    "EUR": rates.get("EUR", DEFAULT_RATES["EUR"]),
                    "RSD": rates.get("RSD", DEFAULT_RATES["RSD"]),
                }
                cls._last_fetch_date = today
                logger.info(f"Uspešno učitani kursevi valuta: {cls._rates_cache}")
            else:
                logger.error(f"Greška pri preuzimanju kurseva, status: {response.status_code}")
        except Exception as e:
            logger.warning(f"Izuzetak pri povezivanju sa API-jem za kurseve: {e}")

        if not cls._rates_cache:
            cls._rates_cache = dict(DEFAULT_RATES)

    @classmethod
    def get_rate(cls, currency: str) -> float:
        """Kurs 1 USD prema trazenoj valuti, uz lazy osvezavanje."""
        cls.update_exchange_rates()
        return cls._rates_cache.get(currency, DEFAULT_RATES[currency])

    @classmethod
    def eur_to_rsd_rate(cls) -> float:
        eur_rate = cls.get_rate("EUR")
        rsd_rate = cls.get_rate("RSD")
        return rsd_rate / eur_rate if eur_rate > 0 else DEFAULT_RATES["RSD"]

    @classmethod
    def convert_price(cls, price_usd: float) -> tuple[float, float]:
        eur_rate = cls.get_rate("EUR")

        if not price_usd or price_usd <= 0:
            return 0.0, 0.0

        price_eur = price_usd * eur_rate
        price_rsd = price_eur * cls.eur_to_rsd_rate()

        return round(price_eur, 2), round(price_rsd, 2)


def calculate_card_price_rsd(price_eur: float) -> int:
    """Prodajna cena u dinarima: kurs + marza po cenovnom rangu, zaokruzeno na 10."""
    if price_eur is None or price_eur <= 0:
        return 0

    effective_exchange_rate = PricingService.eur_to_rsd_rate()

    if price_eur < 0.35:
        return 50
    elif price_eur < 2.00:
        raw_price = price_eur * effective_exchange_rate + 15
    elif price_eur < 5.00:
        raw_price = price_eur * effective_exchange_rate + 30
    elif price_eur < 10.00:
        raw_price = price_eur * effective_exchange_rate + 60
    elif price_eur < 25.00:
        raw_price = price_eur * effective_exchange_rate * 1.10
    elif price_eur < 50.00:
        raw_price = price_eur * effective_exchange_rate * 1.07
    elif price_eur < 100.00:
        raw_price = price_eur * effective_exchange_rate * 1.05
    else:
        raw_price = price_eur * effective_exchange_rate * 1.03

    return math.ceil(raw_price / 10.0) * 10
