"""Korak 1 posla: Scryfall bulk fajl -> staging -> catalog.Card.

Pokretanje:
    python -m tools.etl_scryfall --database CardTracker

Kredencijali idu kroz CARDTRACKER_MSSQL_* promenljive okruzenja, ne kroz
argumente - argumenti se vide u listi procesa i u logu SQL Agent-a.
"""

import argparse
import json
import logging
import os
import sys

from downloader import ScryfallDownloader
from models.card import Card
from services.mssql import ConnectionSettings, connection, sql

logger = logging.getLogger("etl.scryfall")

BATCH_SIZE = 2000

STAGING_COLUMNS = (
    "ScryfallId", "Name", "SetCode", "SetName", "CollectorNumber", "TypeLine",
    "Rarity", "Cmc", "Colors", "Layout", "ImageUrl",
    "PriceUsd", "PriceUsdFoil", "PriceEur", "PriceEurFoil",
)


def _image_url(card_data: dict) -> str | None:
    uris = card_data.get("image_uris")
    if not uris and "card_faces" in card_data:
        faces = card_data.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            uris = faces[0].get("image_uris")
    return uris.get("normal") if isinstance(uris, dict) else None


def _staging_row(card_data: dict) -> tuple:
    prices = card_data.get("prices") or {}
    colors = card_data.get("colors") or []
    return (
        card_data.get("id"),
        card_data.get("name"),
        card_data.get("set"),
        card_data.get("set_name"),
        str(card_data.get("collector_number", "")),
        card_data.get("type_line"),
        card_data.get("rarity"),
        str(card_data.get("cmc", 0)),
        "".join(colors) if colors else "C",
        card_data.get("layout"),
        _image_url(card_data),
        prices.get("usd"),
        prices.get("usd_foil"),
        prices.get("eur"),
        prices.get("eur_foil"),
    )


def load_jsonl_into_staging(conn, jsonl_path: str, load_run_id: int) -> int:
    """Puni staging.ScryfallCard. Vraca broj ubacenih redova."""
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE staging.ScryfallCard")

    placeholders = ", ".join(["%s"] * (len(STAGING_COLUMNS) + 1))
    insert_sql = (
        f"INSERT INTO staging.ScryfallCard (LoadRunId, {', '.join(STAGING_COLUMNS)}) "
        f"VALUES ({placeholders})"
    )
    insert_sql = sql(conn, insert_sql)

    batch, total = [], 0

    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                card_data = json.loads(line)
            except ValueError:
                continue

            # Ista pravila kao u aplikaciji: bez cene karta nas ne zanima.
            if not Card.has_valid_price(card_data):
                continue

            batch.append((load_run_id, *_staging_row(card_data)))

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(insert_sql, batch)
                total += len(batch)
                batch = []
                logger.info("Ubačeno %s redova u staging...", f"{total:,}")

    if batch:
        cursor.executemany(insert_sql, batch)
        total += len(batch)

    conn.commit()
    logger.info("Staging popunjen: %s redova.", f"{total:,}")
    return total


def run(jsonl_path: str, settings: ConnectionSettings, download: bool = True) -> int:
    if download and not os.path.exists(jsonl_path):
        logger.info("Preuzimam Scryfall bulk podatke...")
        if not ScryfallDownloader().download_and_extract(jsonl_path):
            logger.error("Preuzimanje nije uspelo.")
            return 1

    if not os.path.exists(jsonl_path):
        logger.error("Ulazni fajl ne postoji: %s", jsonl_path)
        return 1

    with connection(settings) as conn:
        cursor = conn.cursor()

        cursor.execute(
            sql(conn,
                "DECLARE @id BIGINT; "
                "EXEC etl.usp_StartLoadRun @JobName='SCRYFALL_CATALOG', "
                "@SourceName=%s, @LoadRunId=@id OUTPUT; "
                "SELECT @id"),
            (jsonl_path,),
        )
        load_run_id = int(cursor.fetchone()[0])
        logger.info("LoadRunId = %s", load_run_id)

        load_jsonl_into_staging(conn, jsonl_path, load_run_id)

        logger.info("Spajam staging u katalog...")
        cursor.execute(
            sql(conn, "EXEC catalog.usp_MergeScryfallStaging @LoadRunId = %s"),
            (load_run_id,),
        )
        summary = cursor.fetchone()
        conn.commit()

    logger.info(
        "Gotovo. Pročitano=%s ubačeno=%s ažurirano=%s odbijeno=%s",
        summary[0], summary[1], summary[2], summary[3],
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Učitaj Scryfall katalog u SQL Server.")
    parser.add_argument("--database", default=None, help="Naziv baze (podrazumevano CardTracker)")
    parser.add_argument("--file", default="scryfall_default_cards.jsonl", help="Putanja do JSONL fajla")
    parser.add_argument("--no-download", action="store_true", help="Ne preuzimaj, koristi postojeći fajl")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    settings = ConnectionSettings.from_env(database=args.database)
    return run(args.file, settings, download=not args.no_download)


if __name__ == "__main__":
    sys.exit(main())
