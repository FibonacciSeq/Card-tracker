"""Release expired reservations on a fixed interval."""

from __future__ import annotations

import logging
import time

from app.db import SessionLocal
from app.services.card_requests import expire_due_quotes
from app.services.reservations import expire_due_reservations

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 60


def run_once() -> int:
    with SessionLocal() as db:
        count = expire_due_reservations(db)
        quotes = expire_due_quotes(db)
    if count:
        logger.info("Expired %s reservation(s)", count)
    if quotes:
        logger.info("Expired %s special-order quote(s)", quotes)
    return count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Reservation expiry worker started")
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Expiry worker failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
