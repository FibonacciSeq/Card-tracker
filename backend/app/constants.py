"""Single source of truth for shared domain constants.

Values that previously appeared as duplicate string literals in database check
constraints, Pydantic request models, CSV import validation, service logic, and
notification rendering live here once. Literal aliases keep static type checkers
happy while the tuples feed runtime validation and SQL constraints.
"""

from __future__ import annotations

from typing import Literal

# --- Tenants and users ------------------------------------------------------


TenantStatus = Literal["active", "trialing"]
TENANT_ACTIVE_STATUSES: tuple[TenantStatus, ...] = ("active", "trialing")

UserRole = Literal["platform_admin", "owner", "staff", "customer"]
USER_ROLES: tuple[UserRole, ...] = ("platform_admin", "owner", "staff", "customer")

StaffRole = Literal["owner", "staff"]
STAFF_ROLES: tuple[StaffRole, ...] = ("owner", "staff")


# --- Card variants ----------------------------------------------------------


Finish = Literal["nonfoil", "foil", "etched"]
FINISHES: tuple[Finish, ...] = ("nonfoil", "foil", "etched")

Condition = Literal["NM", "LP", "MP", "HP", "DMG"]
CONDITIONS: tuple[Condition, ...] = ("NM", "LP", "MP", "HP", "DMG")

CONDITION_ALIASES: dict[str, Condition] = {
    "near_mint": "NM",
    "lightly_played": "LP",
    "moderately_played": "MP",
    "heavily_played": "HP",
    "damaged": "DMG",
}


# --- Reservations -----------------------------------------------------------


ReservationStatus = Literal["REQUESTED", "CONFIRMED", "READY", "COMPLETED", "CANCELLED", "EXPIRED"]
RESERVATION_STATUSES: tuple[ReservationStatus, ...] = (
    "REQUESTED",
    "CONFIRMED",
    "READY",
    "COMPLETED",
    "CANCELLED",
    "EXPIRED",
)

ReservationStatusUpdate = Literal["CONFIRMED", "READY", "CANCELLED"]

RESERVATION_ACTIVE_STATUSES: tuple[ReservationStatus, ...] = ("REQUESTED", "CONFIRMED", "READY")
RESERVATION_TERMINAL_STATUSES: tuple[ReservationStatus, ...] = ("COMPLETED", "CANCELLED", "EXPIRED")


# --- Special-order requests -------------------------------------------------


CardRequestStatus = Literal[
    "REQUESTED",
    "QUOTED",
    "ACCEPTED",
    "DECLINED",
    "EXPIRED",
    "CONVERTED",
    "CANCELLED",
]
CARD_REQUEST_STATUSES: tuple[CardRequestStatus, ...] = (
    "REQUESTED",
    "QUOTED",
    "ACCEPTED",
    "DECLINED",
    "EXPIRED",
    "CONVERTED",
    "CANCELLED",
)
CARD_REQUEST_ACTIVE_STATUSES: tuple[CardRequestStatus, ...] = ("REQUESTED", "QUOTED", "ACCEPTED")


# --- Stock ledger -----------------------------------------------------------


StockMovementKind = Literal["RESERVE", "RELEASE", "SELL", "SALE", "ADJUST", "IMPORT"]
STOCK_MOVEMENT_KINDS: tuple[StockMovementKind, ...] = ("RESERVE", "RELEASE", "SELL", "SALE", "ADJUST", "IMPORT")
SALE_MOVEMENT_KINDS: tuple[StockMovementKind, ...] = ("SELL", "SALE")


# --- Notifications ----------------------------------------------------------


NotificationStatus = Literal["pending", "retrying", "sent", "skipped", "failed"]
NOTIFICATION_STATUSES: tuple[NotificationStatus, ...] = ("pending", "retrying", "sent", "skipped", "failed")

RESERVATION_CREATED = "RESERVATION_CREATED"
RESERVATION_CONFIRMED = "RESERVATION_CONFIRMED"
RESERVATION_READY = "RESERVATION_READY"
RESERVATION_CANCELLED = "RESERVATION_CANCELLED"
RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
RESERVATION_COMPLETED = "RESERVATION_COMPLETED"
RESERVATION_UPDATED = "RESERVATION_UPDATED"
CARD_REQUEST_CREATED = "CARD_REQUEST_CREATED"
CARD_REQUEST_QUOTED = "CARD_REQUEST_QUOTED"
CARD_REQUEST_EXPIRED = "CARD_REQUEST_EXPIRED"
CARD_REQUEST_DECLINED = "CARD_REQUEST_DECLINED"
CARD_REQUEST_ACCEPTED = "CARD_REQUEST_ACCEPTED"
CARD_REQUEST_CONVERTED = "CARD_REQUEST_CONVERTED"
CARD_REQUEST_CANCELLED = "CARD_REQUEST_CANCELLED"
RESTOCK_AVAILABLE = "RESTOCK_AVAILABLE"

NOTIFICATION_KINDS: tuple[str, ...] = (
    RESERVATION_CREATED,
    RESERVATION_CONFIRMED,
    RESERVATION_READY,
    RESERVATION_CANCELLED,
    RESERVATION_EXPIRED,
    RESERVATION_COMPLETED,
    RESERVATION_UPDATED,
    CARD_REQUEST_CREATED,
    CARD_REQUEST_QUOTED,
    CARD_REQUEST_EXPIRED,
    CARD_REQUEST_DECLINED,
    CARD_REQUEST_ACCEPTED,
    CARD_REQUEST_CONVERTED,
    CARD_REQUEST_CANCELLED,
    RESTOCK_AVAILABLE,
)


# --- Push notifications -----------------------------------------------------


PushPlatform = Literal["ios", "android"]
PUSH_PLATFORMS: tuple[PushPlatform, ...] = ("ios", "android")


# --- Defaults ---------------------------------------------------------------


DEFAULT_LOCALE = "en"
DEFAULT_CURRENCY = "EUR"
DEFAULT_TIMEZONE = "Europe/Belgrade"
DEFAULT_HOLD_HOURS = 24
DEFAULT_ROUNDING_INCREMENT_MINOR = 500
MINOR_UNITS_PER_MAJOR = 100

MAX_HOLD_HOURS = 720
MAX_ARCHIVE_RETENTION_DAYS = 3650
MAX_MARKUP_PERCENT = 10_000

# --- Size limits ------------------------------------------------------------

# PostgreSQL/MySQL signed integer maximum used for money columns.
MAX_PRICE_MINOR = 2_147_483_647
MIN_ROUNDING_INCREMENT_MINOR = 100
MAX_ROUNDING_INCREMENT_MINOR = 2_147_483_600

MAX_STOCK_IMPORT_BYTES = 5 * 1024 * 1024
MAX_STOCK_IMPORT_ROWS = 20_000

# Page sizes. Endpoints serve different clients, so each keeps its own explicit
# bound rather than sharing one global default.
PUBLIC_PAGE_SIZE = 50
PUBLIC_MAX_PAGE_SIZE = 100
ACCOUNT_PAGE_SIZE = 50
ACCOUNT_MAX_PAGE_SIZE = 200
MAX_ACCOUNT_ROWS = 200
STAFF_PAGE_SIZE = 50
STAFF_MAX_PAGE_SIZE = 200
STAFF_CARD_SEARCH_PAGE_SIZE = 25
STAFF_CARD_SEARCH_MAX_PAGE_SIZE = 100
STAFF_STOCK_PAGE_SIZE = 200
STAFF_STOCK_MAX_PAGE_SIZE = 500
STAFF_RESERVATION_PAGE_SIZE = 100
STAFF_RESERVATION_MAX_PAGE_SIZE = 300
STAFF_REQUEST_PAGE_SIZE = 200
STAFF_REQUEST_MAX_PAGE_SIZE = 500


# --- Helpers ----------------------------------------------------------------


def sql_in(column: str, values: tuple[str, ...]) -> str:
    """Render a SQL ``IN (...)`` clause from a tuple of string constants.

    Used to keep model check constraints in sync with the Python literals
    without hand-writing the same value lists twice.
    """
    rendered = ",".join(repr(value) for value in values)
    return f"{column} IN ({rendered})"
