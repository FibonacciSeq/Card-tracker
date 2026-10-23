"""Ulazna tacka za vlasnicku aplikaciju.

Pokretanje:
    python owner_app.py
"""

import logging
import tkinter as tk

from services.catalog_bootstrap import prepare_catalog
from services.shop_database import ShopDatabase
from ui.owner_app import OwnerApp

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def main():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    database = prepare_catalog()
    shop = ShopDatabase()

    root = tk.Tk()

    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(root.attributes, "-topmost", False)

    OwnerApp(root, database, shop)
    root.mainloop()


if __name__ == "__main__":
    main()
