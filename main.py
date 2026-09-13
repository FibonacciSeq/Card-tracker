import logging
import os
import tkinter as tk

from downloader import ScryfallDownloader
from services.card_collection import CardCollection
from services.sqlite_database import SQLiteCardDatabase
from ui.app import ScryfallApp

logger = logging.getLogger(__name__)

DATABASE_FILE = "scryfall_default_cards.jsonl"
COLLECTION_FILE = "my_collection.json"
SQLITE_FILE = "scryfall.db"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Podesava logovanje jednom, na ulaznoj tacki aplikacije."""
    logging.basicConfig(level=level, format=LOG_FORMAT)


def display_app(
    input_filename: str = DATABASE_FILE,
    collection_filename: str = COLLECTION_FILE,
    db_path: str = SQLITE_FILE,
):
    if not os.path.exists(input_filename):
        logger.warning("Fajl nije pronađen. Započinjem prvobitno preuzimanje sa Scryfall-a...")

        downloader = ScryfallDownloader()

        if not downloader.download_and_extract(input_filename):
            logger.error("Preuzimanje baze nije uspelo.")

    database = SQLiteCardDatabase(db_path=db_path, jsonl_path=input_filename)
    collection = CardCollection(collection_filename)

    root = tk.Tk()

    # Podigni prozor iznad ostalih, ali ne ostavljaj ga trajno "topmost".
    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(root.attributes, "-topmost", False)

    ScryfallApp(root, database, collection)

    root.mainloop()


if __name__ == "__main__":
    configure_logging()
    display_app()
