
import openpyxl

from services.card_lookup import as_lookup
from services.spreadsheet import cell, detect_columns


class ExcelImporter:
    """Uvozi kolekciju iz Excel fajla."""

    NAME_KEYWORDS = ["naziv", "name", "kartica", "card", "title"]
    QUANTITY_KEYWORDS = ["količina", "kolicina", "qty", "count", "kom"]

    @classmethod
    def import_file(cls, file_path: str, database, collection) -> tuple[int, list[str]]:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))

        if not rows:
            return 0, []

        header_keywords = {
            "name": cls.NAME_KEYWORDS,
            "quantity": cls.QUANTITY_KEYWORDS,
        }
        start_row, columns = detect_columns(rows, header_keywords)

        lookup = as_lookup(database)

        added_count = 0
        unmatched = []

        for row in rows[start_row:]:
            raw_name = cell(row, columns, "name")

            if not raw_name:
                continue

            if raw_name.lower().startswith(("ukupno", "total", "naziv", "name")):
                continue

            qty = 1
            raw_qty = cell(row, columns, "quantity")

            if raw_qty is not None:
                try:
                    qty = int(float(raw_qty))
                except (ValueError, TypeError):
                    qty = 1

            if qty <= 0:
                continue

            matched_card = lookup.find_cheapest_by_name(raw_name) or lookup.find_by_loose_name(raw_name)

            if matched_card:
                new_card = matched_card.clone(is_foil=False, quantity=qty)
                collection.add_card(new_card)
                added_count += qty
            else:
                unmatched.append(f"{qty}x {raw_name}")

        return added_count, unmatched