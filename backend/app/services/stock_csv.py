"""CSV import and export for shop stock.

Vendors keep their inventory in spreadsheets, so this is the difference between
a five-minute onboarding and typing thousands of rows by hand.

The exported file is the import template: round-tripping it is safe. Import
matches on card identity plus variant (finish/condition/language) and treats the
`quantity` column as the absolute on-hand count, recording an IMPORT movement
for the difference so the ledger stays truthful.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services import restock

COLUMNS = [
    "card_name",
    "set_code",
    "collector_number",
    "finish",
    "condition",
    "language",
    "quantity",
    "price",
    "currency",
    "is_online",
    "available",
]

REQUIRED_COLUMNS = {"set_code", "collector_number", "quantity", "price"}

FINISHES = {"nonfoil", "foil", "etched"}
CONDITIONS = {"NM", "LP", "MP", "HP", "DMG"}
TRUE_VALUES = {"true", "yes", "1", "y"}
FALSE_VALUES = {"false", "no", "0", "n"}

MAX_ROWS = 20_000


@dataclass
class ImportRow:
    line: int
    set_code: str
    collector_number: str
    card_name: str
    finish: str
    condition: str
    language: str
    quantity: int
    price_minor: int
    currency: str
    is_online: bool


@dataclass
class RowError:
    row: int
    message: str
    field: str | None = None


class CsvFormatError(Exception):
    """The file as a whole cannot be processed (missing header, too big, ...)."""


def export_rows(db: Session, tenant_id) -> list[dict[str, str]]:
    stmt = (
        select(models.Stock, models.Card)
        .join(models.Card, models.Card.id == models.Stock.card_id)
        .where(models.Stock.tenant_id == tenant_id)
        .order_by(func.lower(models.Card.name), models.Stock.finish, models.Stock.condition, models.Stock.language)
    )
    rows: list[dict[str, str]] = []
    for stock, card in db.execute(stmt).all():
        rows.append(
            {
                "card_name": card.name,
                "set_code": card.set_code.upper(),
                "collector_number": card.collector_number,
                "finish": stock.finish,
                "condition": stock.condition,
                "language": stock.language,
                "quantity": str(stock.quantity),
                "price": f"{Decimal(stock.price_minor) / 100:.2f}",
                "currency": stock.currency,
                "is_online": "true" if stock.is_online else "false",
                "available": str(max(0, stock.quantity - stock.reserved)),
            }
        )
    return rows


def render_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in COLUMNS})
    return buffer.getvalue()


def parse_csv(text: str, tenant_currency: str) -> tuple[list[ImportRow], list[RowError]]:
    # Excel saves UTF-8 with a BOM; strip it so the first header matches.
    text = text.lstrip("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
    except csv.Error as exc:
        raise CsvFormatError("The file is not readable as CSV.") from exc

    if not fieldnames:
        raise CsvFormatError("The file is empty. Export your stock first to get the template.")
    missing = REQUIRED_COLUMNS - set(fieldnames)
    if missing:
        raise CsvFormatError(f"Missing required column(s): {', '.join(sorted(missing))}.")

    reader.fieldnames = fieldnames
    rows: list[ImportRow] = []
    errors: list[RowError] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for index, raw in enumerate(reader, start=2):  # row 2 is the first data row in a spreadsheet
        if index - 1 > MAX_ROWS:
            raise CsvFormatError(f"Files are limited to {MAX_ROWS} rows. Split the import into batches.")
        if not any((value or "").strip() for value in raw.values()):
            continue

        parsed, row_errors = _parse_row(index, raw, tenant_currency)
        if row_errors:
            errors.extend(row_errors)
            continue
        assert parsed is not None
        key = (
            parsed.set_code.upper(),
            parsed.collector_number.upper(),
            parsed.finish,
            parsed.condition,
            parsed.language,
        )
        if key in seen:
            errors.append(RowError(index, "Duplicate row for the same card and variant in this file."))
            continue
        seen.add(key)
        rows.append(parsed)

    return rows, errors


def _parse_row(line: int, raw: dict[str, str | None], tenant_currency: str) -> tuple[ImportRow | None, list[RowError]]:
    errors: list[RowError] = []

    def value(name: str) -> str:
        return (raw.get(name) or "").strip()

    set_code = value("set_code")
    if not set_code:
        errors.append(RowError(line, "set_code is required.", "set_code"))
    collector_number = value("collector_number")
    if not collector_number:
        errors.append(RowError(line, "collector_number is required.", "collector_number"))

    finish = value("finish").lower() or "nonfoil"
    if finish not in FINISHES:
        errors.append(RowError(line, f"finish must be one of {', '.join(sorted(FINISHES))}.", "finish"))

    condition = value("condition").upper() or "NM"
    if condition not in CONDITIONS:
        errors.append(RowError(line, f"condition must be one of {', '.join(sorted(CONDITIONS))}.", "condition"))

    language = (value("language") or "en").lower()
    if not language.isalpha() or not 2 <= len(language) <= 5:
        errors.append(RowError(line, "language must be a short code such as en.", "language"))

    quantity = 0
    raw_quantity = value("quantity")
    try:
        quantity = int(raw_quantity)
        if quantity < 0:
            raise ValueError
    except ValueError:
        errors.append(RowError(line, "quantity must be a whole number of zero or more.", "quantity"))

    price_minor = 0
    raw_price = value("price").replace(",", ".") if value("price") else ""
    try:
        price = Decimal(raw_price)
        if price < 0:
            raise ValueError
        if -price.as_tuple().exponent > 2:  # type: ignore[operator]
            raise InvalidOperation
        price_minor = int(price * 100)
    except (InvalidOperation, ValueError):
        errors.append(RowError(line, "price must be a positive amount with at most two decimals.", "price"))

    currency = (value("currency") or tenant_currency).upper()
    if currency != tenant_currency.upper():
        errors.append(RowError(line, f"currency must be {tenant_currency} for this shop.", "currency"))

    is_online = True
    raw_online = value("is_online").lower()
    if raw_online:
        if raw_online in TRUE_VALUES:
            is_online = True
        elif raw_online in FALSE_VALUES:
            is_online = False
        else:
            errors.append(RowError(line, "is_online must be true or false.", "is_online"))

    if errors:
        return None, errors

    return (
        ImportRow(
            line=line,
            set_code=set_code,
            collector_number=collector_number,
            card_name=value("card_name"),
            finish=finish,
            condition=condition,
            language=language,
            quantity=quantity,
            price_minor=price_minor,
            currency=currency,
            is_online=is_online,
        ),
        [],
    )


def apply_rows(
    db: Session,
    tenant: models.Tenant,
    actor_id,
    rows: list[ImportRow],
    *,
    dry_run: bool,
) -> tuple[int, int, int, list[RowError]]:
    """Apply parsed rows and return (created, updated, unchanged, errors)."""
    errors: list[RowError] = []
    created = updated = unchanged = 0

    set_codes = {row.set_code.upper() for row in rows}
    cards_by_key: dict[tuple[str, str], models.Card] = {}
    if set_codes:
        cards = db.scalars(select(models.Card).where(func.upper(models.Card.set_code).in_(set_codes))).all()
        for catalog_card in cards:
            cards_by_key[(catalog_card.set_code.upper(), catalog_card.collector_number.upper())] = catalog_card

    stock_rows = db.scalars(select(models.Stock).where(models.Stock.tenant_id == tenant.id)).all()
    stock_by_key: dict[tuple, models.Stock] = {
        (stock.card_id, stock.finish, stock.condition, stock.language): stock for stock in stock_rows
    }

    for row in rows:
        card = cards_by_key.get((row.set_code.upper(), row.collector_number.upper()))
        if card is None:
            errors.append(
                RowError(
                    row.line,
                    f"No catalog card for {row.set_code.upper()} #{row.collector_number}. "
                    "Check the set code and collector number.",
                    "set_code",
                )
            )
            continue

        key = (card.id, row.finish, row.condition, row.language)
        stock = stock_by_key.get(key)

        if stock is None:
            created += 1
            if dry_run:
                continue
            stock = models.Stock(
                tenant_id=tenant.id,
                card_id=card.id,
                finish=row.finish,
                condition=row.condition,
                language=row.language,
                quantity=row.quantity,
                reserved=0,
                price_minor=row.price_minor,
                currency=row.currency,
                is_online=row.is_online,
            )
            db.add(stock)
            db.flush()
            stock_by_key[key] = stock
            if row.quantity:
                db.add(_movement(tenant.id, stock, actor_id, row.quantity, "CSV import: new card"))
            restock.notify_waiting(db, tenant, stock)
            continue

        if row.quantity < stock.reserved:
            errors.append(
                RowError(
                    row.line,
                    f"quantity would drop below the {stock.reserved} reserved copies.",
                    "quantity",
                )
            )
            continue

        if stock.quantity == row.quantity and stock.price_minor == row.price_minor and stock.is_online == row.is_online:
            unchanged += 1
            continue

        updated += 1
        if dry_run:
            continue

        delta = row.quantity - stock.quantity
        stock.quantity = row.quantity
        stock.price_minor = row.price_minor
        stock.is_online = row.is_online
        stock.updated_at = models.utcnow()
        if delta:
            db.add(_movement(tenant.id, stock, actor_id, delta, "CSV import"))
        restock.notify_waiting(db, tenant, stock)

    return created, updated, unchanged, errors


def _movement(tenant_id, stock: models.Stock, actor_id, delta: int, reason: str) -> models.StockMovement:
    return models.StockMovement(
        tenant_id=tenant_id,
        stock_id=stock.id,
        kind="IMPORT",
        on_hand_delta=delta,
        reserved_delta=0,
        on_hand_after=stock.quantity,
        reserved_after=stock.reserved,
        actor_id=actor_id,
        reason=reason,
    )
