
import openpyxl

from services.card_lookup import as_lookup


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

        name_idx = -1
        qty_idx = -1
        start_row = 0

        for i, row in enumerate(rows[:10]):
            if not row:
                continue

            # Indeks mora da prati stvarnu kolonu: preskakanje praznih celija
            # bi pomerilo numeraciju i citali bismo pogresnu kolonu.
            for j, value in enumerate(row):
                if value is None:
                    continue

                val = str(value).strip().lower()

                if name_idx == -1 and any(k in val for k in cls.NAME_KEYWORDS):
                    name_idx = j
                elif qty_idx == -1 and any(k in val for k in cls.QUANTITY_KEYWORDS):
                    qty_idx = j

            if name_idx != -1:
                start_row = i + 1
                break

        if name_idx == -1:
            name_idx = 0
            qty_idx = 1 if len(rows[0]) > 1 else -1
            start_row = 0

        lookup = as_lookup(database)

        added_count = 0
        unmatched = []

        for row in rows[start_row:]:
            if not row or name_idx >= len(row) or row[name_idx] is None:
                continue

            raw_name = str(row[name_idx]).strip()

            if not raw_name:
                continue

            if raw_name.lower().startswith(("ukupno", "total", "naziv", "name")):
                continue

            qty = 1

            if qty_idx != -1 and qty_idx < len(row) and row[qty_idx] is not None:
                try:
                    qty = int(float(str(row[qty_idx]).strip()))
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