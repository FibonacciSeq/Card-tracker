"""Stream a Scryfall default-cards JSONL file into the global card catalog."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Card

logger = logging.getLogger(__name__)


def _images(obj: dict[str, Any]) -> dict[str, str]:
    images = obj.get("image_uris")
    if not images:
        faces = obj.get("card_faces") or []
        if faces:
            images = faces[0].get("image_uris")
    return images or {}


def _card_fields(obj: dict[str, Any], store_raw: bool) -> dict[str, Any]:
    images = _images(obj)
    faces = obj.get("card_faces") or []
    colors = obj.get("colors")
    if colors is None and faces:
        colors = faces[0].get("colors")
    return {
        "provider": "scryfall",
        "provider_card_id": str(obj["id"]),
        "name": str(obj.get("name") or ""),
        "set_code": str(obj.get("set") or ""),
        "set_name": str(obj.get("set_name") or ""),
        "collector_number": str(obj.get("collector_number") or ""),
        "rarity": str(obj.get("rarity") or ""),
        "type_line": str(obj.get("type_line") or ""),
        "colors": colors or [],
        "image_small": images.get("small"),
        "image_normal": images.get("normal"),
        "image_large": images.get("large"),
        "raw": obj if store_raw else {},
    }


def run(path: Path, limit: int | None, batch_size: int, store_raw: bool) -> int:
    processed = 0
    created = 0
    updated = 0

    with path.open("r", encoding="utf-8") as handle, SessionLocal() as db:
        for line in handle:
            if limit is not None and processed >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line")
                continue
            if obj.get("object") not in (None, "card"):
                continue
            if "id" not in obj:
                continue

            provider_id = str(obj["id"])
            existing = db.scalar(
                select(Card).where(
                    Card.provider == "scryfall",
                    Card.provider_card_id == provider_id,
                )
            )
            fields = _card_fields(obj, store_raw)
            if existing is None:
                db.add(Card(**fields))
                created += 1
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
                updated += 1

            processed += 1
            if processed % batch_size == 0:
                db.commit()
                logger.info("Imported %s cards", processed)

        db.commit()

    logger.info("Done: %s processed, %s created, %s updated", processed, created, updated)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True, help="Scryfall JSONL file")
    parser.add_argument("--limit", type=int, default=None, help="Only import the first N cards")
    parser.add_argument("--batch", type=int, default=500, help="Commit every N cards")
    parser.add_argument("--store-raw", action="store_true", help="Store the full Scryfall object")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.path.exists():
        raise SystemExit(f"File not found: {args.path}")
    run(args.path, args.limit, args.batch, args.store_raw)


if __name__ == "__main__":
    main()
