"""Prepoznavanje kolona u Excel/CSV tabelama.

Tabele stizu sa raznim zaglavljima ("Naziv", "Card Name", "Kolicina", "Qty"),
sa praznim kolonama i sa zaglavljem koje nije u prvom redu. Ovde je ta logika
na jednom mestu, da je ne bismo pisali iznova za svaki uvoz.
"""

from typing import Any

# Podrazumevani sinonimi po polju.
DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "name": ["naziv", "name", "kartica", "card", "title"],
    "quantity": ["količina", "kolicina", "qty", "count", "kom"],
    "set_code": ["set", "edition", "izdanje"],
    "collector_number": ["collector", "broj", "number", "card #", "#"],
    "is_foil": ["foil"],
    "condition": ["stanje", "condition", "cond"],
    "language": ["jezik", "language", "lang"],
    "location": ["lokacija", "location", "kutija", "box"],
    "unit_cost": ["nabavna", "cost", "cena nabavke", "purchase"],
}


def detect_columns(
    rows: list[tuple],
    keywords: dict[str, list[str]] | None = None,
    max_scan: int = 10,
) -> tuple[int, dict[str, int]]:
    """Nadji red zaglavlja i mapiraj polje -> indeks kolone.

    Vraca (indeks prvog reda sa podacima, mapa polja).

    Indeks kolone prati STVARNU poziciju u redu: prazne celije se preskacu,
    ali ne pomeraju numeraciju.
    """
    keywords = keywords or DEFAULT_KEYWORDS
    mapping: dict[str, int] = {}

    for row_index, row in enumerate(rows[:max_scan]):
        if not row:
            continue

        found: dict[str, int] = {}

        for col_index, value in enumerate(row):
            if value is None:
                continue

            text = str(value).strip().lower()
            if not text:
                continue

            for field, synonyms in keywords.items():
                # Prvi pogodak po polju pobedjuje: "Card Name" pre "Card #".
                if field not in found and any(word in text for word in synonyms):
                    found[field] = col_index
                    break

        if "name" in found:
            return row_index + 1, found

        mapping = found or mapping

    # Bez prepoznatog zaglavlja: pretpostavi naziv u prvoj, kolicinu u drugoj.
    fallback = {"name": 0}
    if rows and len(rows[0]) > 1:
        fallback["quantity"] = 1
    return 0, fallback


def cell(row: tuple, mapping: dict[str, int], field: str) -> Any | None:
    """Vrednost polja iz reda, ili None ako kolone nema."""
    index = mapping.get(field)
    if index is None or index >= len(row):
        return None
    value = row[index]
    if value is None:
        return None
    text = str(value).strip()
    return text or None
