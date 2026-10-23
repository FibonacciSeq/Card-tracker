"""Shared local Scryfall catalog preparation for the desktop apps."""

import logging
import os

from downloader import ScryfallDownloader
from services.sqlite_database import SQLiteCardDatabase

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_JSONL = "scryfall_default_cards.jsonl"
DEFAULT_CATALOG_DB = "scryfall.db"


def prepare_catalog(
    *,
    db_path: str = DEFAULT_CATALOG_DB,
    jsonl_path: str = DEFAULT_CATALOG_JSONL,
) -> SQLiteCardDatabase:
    """Open the local catalog and download the source file only when needed."""
    database = SQLiteCardDatabase(db_path=db_path, jsonl_path=jsonl_path)

    if database.count() == 0 and not os.path.exists(jsonl_path):
        logger.warning("Katalog je prazan. Preuzimam Scryfall bazu...")
        if not ScryfallDownloader().download_and_extract(jsonl_path):
            logger.error("Preuzimanje Scryfall baze nije uspelo.")

    return database
