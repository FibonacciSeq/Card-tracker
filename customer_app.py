"""Ulazna tacka za kupacku aplikaciju.

Pokretanje:
    python customer_app.py
"""

import logging
import tkinter as tk

from services.catalog_bootstrap import prepare_catalog
from services.shop_database import ShopDatabase
from ui.customer_app import CustomerApp

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def main():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    database = prepare_catalog()
    shop = ShopDatabase()

    root = tk.Tk()

    # Podigni prozor iznad ostalih samo na startu.
    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(root.attributes, "-topmost", False)

    CustomerApp(root, database, shop)
    root.mainloop()


if __name__ == "__main__":
    main()
