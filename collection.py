import json
import logging
import os
from typing import Any

import openpyxl

from services.card_lookup import as_lookup

logger = logging.getLogger(__name__)


class CollectionStorage:

    @classmethod
    def save_to_file(cls, collection_list: list[Any], filename: str) -> tuple[bool, str]:
        temp_filename = filename + ".tmp"
        try:
            saved_data = []
            for card in collection_list:
                card_dict = card.to_dict() if hasattr(card, "to_dict") else card
                saved_data.append({
                    "name": card_dict.get("name", ""),
                    "set": card_dict.get("set", card_dict.get("set_name", "")),
                    "collector_number": str(card_dict.get("collector_number", "")),
                    "quantity": card_dict.get("quantity", 1),
                    "is_foil": card_dict.get("is_foil", False),
                    "cmc": card_dict.get("cmc", 0),
                    "colors": card_dict.get("colors", ""),
                    "type": card_dict.get("type", card_dict.get("type_line", "")),
                    "rarity": card_dict.get("rarity", ""),
                    "price_normal": card_dict.get("price_normal", "N/A"),
                    "price_foil": card_dict.get("price_foil", "N/A"),
                    "price_numeric": card_dict.get("price_numeric", 0.0),
                    "price_rsd": card_dict.get("price_rsd", 0.0)
                })

            with open(temp_filename, "w", encoding="utf-8") as f:
                json.dump(saved_data, f, ensure_ascii=False, indent=4)

            os.replace(temp_filename, filename)
            return True, filename

        except Exception as e:
            logger.error(f"Greška pri čuvanju kolekcije: {e}")
            if os.path.exists(temp_filename):
                try:
                    os.remove(temp_filename)
                except OSError:
                    pass
            return False, filename

    @classmethod
    def load_from_file(cls, filename: str, card_source: Any) -> list[Any]:
      
        if not os.path.exists(filename):
            # Provera ako je prošireno bez ekstenzije
            if os.path.exists(filename + ".xlsx"):
                filename += ".xlsx"
            elif os.path.exists(filename + ".json"):
                filename += ".json"
            else:
                return []

        if filename.endswith(".xlsx"):
            return cls._load_from_excel(filename, card_source)
        
        return cls._load_from_json(filename, card_source)

    @classmethod
    def _load_from_json(cls, filename: str, card_source: Any) -> list[Any]:
        lookup = as_lookup(card_source)
        loaded_collection = []

        try:
            with open(filename, encoding="utf-8") as f:
                saved_data = json.load(f)

            for item in saved_data:
                exact_key = (
                    item.get("name", "").lower(),
                    item.get("set", "").lower(),
                    str(item.get("collector_number", ""))
                )
                name_key = item.get("name", "").lower()
                qty = item.get("quantity", 1)
                is_foil = item.get("is_foil", False)

                found_card = lookup.find_exact(*exact_key) or lookup.find_cheapest_by_name(name_key)

                if found_card:
                    if hasattr(found_card, "clone"):
                        card_clone = found_card.clone(is_foil=is_foil, quantity=qty)
                        card_clone.quantity = qty
                        loaded_collection.append(card_clone)
                    else:
                        card_copy = found_card.copy() if isinstance(found_card, dict) else dict(found_card)
                        card_copy["quantity"] = qty
                        card_copy["is_foil"] = is_foil
                        loaded_collection.append(card_copy)

        except Exception as e:
            logger.error(f"Greška pri učitavanju JSON kolekcije: {e}")

        return loaded_collection

    
    @classmethod
    def _load_from_excel(cls, filename: str, card_source: Any) -> list[Any]:
        try:
            wb = openpyxl.load_workbook(filename=filename, data_only=True)
            sheet = wb.active
        except Exception as e:
            logger.error(f"Greška pri čitanju Excel fajla '{filename}': {e}")
            return []

        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []

        # Detekcija indeksa kolona iz zaglavlja (prvi red)
        header = [str(cell).strip().lower() if cell is not None else "" for cell in rows[0]]
        
        col_name = cls._find_column_index(header, ["naziv kartice", "name", "card name", "naziv"])
        col_set = cls._find_column_index(header, ["set iz kog je kartica", "set", "set code", "edition"])
        col_num = cls._find_column_index(header, ["kolekcijski broj kartice", "collector number", "collector_number", "number", "card #", "#"])
        col_qty = cls._find_column_index(header, ["kolicina", "quantity", "qty", "count"])

        if col_name is None:
            logger.error("Excel fajl ne sadrži prepoznatljivu kolonu sa nazivom kartice.")
            return []

        lookup = as_lookup(card_source)
        loaded_collection = []

        for row in rows[1:]:
            if not row or row[col_name] is None:
                continue

            name = str(row[col_name]).strip()
            if not name:
                continue

            set_code = str(row[col_set]).strip().lower() if col_set is not None and row[col_set] is not None else ""
            coll_num = str(row[col_num]).strip() if col_num is not None and row[col_num] is not None else ""
            
            # Ako u Excelu postoji kolona za količinu, uzimamo taj broj, inače 1
            qty = 1
            if col_qty is not None and row[col_qty] is not None:
                try:
                    qty = int(row[col_qty])
                except (ValueError, TypeError):
                    qty = 1

            exact_key = (name.lower(), set_code, coll_num)
            name_key = name.lower()

            found_card = None
            if set_code and coll_num:
                found_card = lookup.find_exact(*exact_key)
            if not found_card:
                found_card = lookup.find_cheapest_by_name(name_key)

            if found_card:
                loaded_collection.append(cls._with_quantity(found_card, qty))

        return loaded_collection

    @staticmethod
    def _with_quantity(card: Any, qty: int, is_foil: bool = False) -> Any:
        """Jedan unos sa kolicinom, nikad vise referenci na isti objekat."""
        if hasattr(card, "clone"):
            return card.clone(is_foil=is_foil, quantity=qty)

        card_copy = card.copy() if isinstance(card, dict) else dict(card)
        card_copy["quantity"] = qty
        card_copy["is_foil"] = is_foil
        return card_copy

    @staticmethod
    def _find_column_index(header: list[str], possible_names: list[str]) -> int | None:
        for name in possible_names:
            if name in header:
                return header.index(name)
        return None
