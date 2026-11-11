"""Pydantic request and response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Money(BaseModel):
    amount_minor: int
    currency: str


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    locale: str
    currency: str
    timezone: str
    brand_name: str | None = None
    logo_url: str | None = None
    colors: dict = Field(default_factory=dict)
    hero: dict = Field(default_factory=dict)
    contact: dict = Field(default_factory=dict)
    hours: dict = Field(default_factory=dict)
    payment_instructions: str = ""
    hold_hours: int = 24
    allow_backorders: bool = False
    directory_opt_in: bool = False


class StaffShopOut(ShopOut):
    """Staff view: adds settings that must not appear on the public profile."""

    notification_email: EmailStr | None = None
    scryfall_pricing_enabled: bool = False
    scryfall_min_price_minor: int = 0
    scryfall_markup_percent: int = 0
    scryfall_rounding_increment: int = 5
    repriced_stock: int | None = None
    stock_without_scryfall_prices: int | None = None
    archive_retention_days: int = 0


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    set_code: str
    set_name: str
    collector_number: str
    rarity: str
    type_line: str
    image_small: str | None = None
    image_normal: str | None = None
    image_large: str | None = None


class StockItemOut(BaseModel):
    stock_id: uuid.UUID
    card: CardOut
    finish: str
    condition: str
    language: str
    price: Money
    available: int
    is_online: bool
    updated_at: datetime


class StockListOut(BaseModel):
    items: list[StockItemOut]
    next_cursor: str | None = None


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(default="", max_length=50)


class ReservationItemIn(BaseModel):
    stock_id: uuid.UUID
    quantity: int = Field(gt=0, le=999)


class ReservationCreate(BaseModel):
    customer: CustomerIn
    note: str = Field(default="", max_length=2000)
    items: list[ReservationItemIn] = Field(min_length=1, max_length=50)


class ReservationLineOut(BaseModel):
    line_id: uuid.UUID
    stock_id: uuid.UUID | None
    name: str
    set_code: str
    collector_number: str
    finish: str
    condition: str
    language: str
    quantity: int
    completed_quantity: int
    cancelled_quantity: int
    unit_price: Money


class ReservationOut(BaseModel):
    id: uuid.UUID
    public_ref: str
    status: str
    expires_at: datetime
    created_at: datetime
    total: Money
    shop: dict
    customer_name: str
    lines: list[ReservationLineOut]
    access_token: str | None = None


class StaffReservationOut(ReservationOut):
    """Staff view: adds the contact details and note needed to act on a hold."""

    customer_email: EmailStr
    customer_phone: str
    note: str


class ReservationSummaryOut(BaseModel):
    id: uuid.UUID
    public_ref: str
    customer_name: str
    status: str
    expires_at: datetime
    created_at: datetime
    total: Money
    line_count: int


class StaffLoginIn(BaseModel):
    tenant_slug: str
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class StaffMeOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    role: str
    display_name: str | None = None


class OtpRequestIn(BaseModel):
    email: EmailStr


class OtpRequestOut(BaseModel):
    expires_in: int
    resend_after: int
    debug_code: str | None = None


class OtpVerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class EmailChangeRequestIn(BaseModel):
    email: EmailStr


class EmailChangeVerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class CustomerRefreshIn(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)


class CustomerLogoutIn(BaseModel):
    """Optional body for a single-device logout.

    Omitting the refresh token keeps the legacy account-wide logout behavior for
    old clients. The mobile app always sends the current device's token.
    """

    refresh_token: str | None = Field(default=None, min_length=16, max_length=512)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str | None = None
    phone: str | None = None
    push_notifications_enabled: bool = True
    email_notifications_enabled: bool = True
    quiet_hours_enabled: bool = False
    notifications_opt_out: bool = False
    email_verified_at: datetime | None = None
    created_at: datetime


class CustomerProfileUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    push_notifications_enabled: bool | None = None
    email_notifications_enabled: bool | None = None
    quiet_hours_enabled: bool | None = None
    notifications_opt_out: bool | None = None


class ClaimedOut(BaseModel):
    reservations: int = 0
    restock_alerts: int = 0
    card_requests: int = 0


class CustomerTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    refresh_expires_in: int | None = None
    is_new_account: bool
    customer: CustomerOut
    claimed: ClaimedOut


class PushTokenIn(BaseModel):
    token: str = Field(min_length=16, max_length=4096)
    platform: Literal["ios", "android"]


class PushTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None
    failure_count: int = 0
    last_failure_at: datetime | None = None
    last_error: str | None = None


class PushTokenListOut(BaseModel):
    items: list[PushTokenOut]


class MeNotificationOut(BaseModel):
    id: int
    kind: str
    channel: str
    status: Literal["pending", "retrying", "sent", "skipped", "failed"]
    title: str
    shop: dict
    attempts: int
    created_at: datetime
    sent_at: datetime | None = None
    next_attempt_at: datetime | None = None
    error: str | None = None


class MeNotificationListOut(BaseModel):
    items: list[MeNotificationOut]
    next_cursor: str | None = None


class MeReservationSummaryOut(ReservationSummaryOut):
    shop: dict


class MeReservationListOut(BaseModel):
    items: list[MeReservationSummaryOut]


class MeRestockAlertOut(BaseModel):
    id: uuid.UUID
    card_id: uuid.UUID
    stock_id: uuid.UUID | None = None
    card_name: str
    set_code: str
    collector_number: str
    finish: str
    condition: str
    language: str
    email: EmailStr
    shop: dict
    created_at: datetime
    notified_at: datetime | None = None


class MeRestockAlertListOut(BaseModel):
    items: list[MeRestockAlertOut]


class StaffStockOut(BaseModel):
    stock_id: uuid.UUID
    card: CardOut
    finish: str
    condition: str
    language: str
    on_hand: int
    reserved: int
    available: int
    sold_30d: int
    restock_waiting: int = 0
    price: Money
    is_online: bool
    archived_at: datetime | None = None
    updated_at: datetime


class StaffStockListOut(BaseModel):
    items: list[StaffStockOut]


class StockArchiveResultOut(BaseModel):
    archived: int
    reserved: int


class StockDeleteResultOut(BaseModel):
    deleted: int
    kept: int = 0


class StockCreateIn(BaseModel):
    card_id: uuid.UUID
    finish: Literal["nonfoil", "foil", "etched"] = "nonfoil"
    condition: Literal["NM", "LP", "MP", "HP", "DMG"] = "NM"
    language: str = "en"
    quantity: int = Field(default=0, ge=0)
    price_minor: int = Field(default=0, ge=0)
    currency: str | None = None
    is_online: bool = True


class StockUpdateIn(BaseModel):
    quantity: int | None = Field(default=None, ge=0)
    price_minor: int | None = Field(default=None, ge=0)
    is_online: bool | None = None


class StockAdjustIn(BaseModel):
    delta: int
    reason: str = Field(default="manual adjustment", max_length=500)


class StockSellIn(BaseModel):
    quantity: int = Field(gt=0)
    reason: str = Field(default="in-store sale", max_length=500)


class StatusUpdateIn(BaseModel):
    status: Literal["CONFIRMED", "READY", "CANCELLED"]
    reason: str | None = Field(default=None, max_length=2000)


class CompleteLineIn(BaseModel):
    line_id: uuid.UUID
    complete_quantity: int = Field(default=0, ge=0)
    cancel_quantity: int = Field(default=0, ge=0)


class CompleteIn(BaseModel):
    lines: list[CompleteLineIn] | None = None


class RestockAlertCreateIn(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=200)
    card_id: uuid.UUID
    finish: Literal["nonfoil", "foil", "etched"] = "nonfoil"
    condition: Literal["NM", "LP", "MP", "HP", "DMG"] = "NM"
    language: str = Field(default="en", min_length=2, max_length=5)


class RestockUnsubscribeIn(BaseModel):
    email: EmailStr


class RestockAlertOut(BaseModel):
    id: uuid.UUID
    card_id: uuid.UUID
    email: EmailStr
    finish: str
    condition: str
    language: str
    already_subscribed: bool = False
    # Returned once at subscribe time; used by the app to manage the alert.
    manage_token: str | None = None
    created_at: datetime


class CardRequestCreateIn(BaseModel):
    customer: CustomerIn
    card_id: uuid.UUID | None = None
    requested_name: str = Field(default="", max_length=300)
    set_code: str = Field(default="", max_length=20)
    collector_number: str = Field(default="", max_length=40)
    finish: Literal["nonfoil", "foil", "etched"] = "nonfoil"
    condition: Literal["NM", "LP", "MP", "HP", "DMG"] = "NM"
    language: str = Field(default="en", min_length=2, max_length=5)
    quantity: int = Field(default=1, ge=1, le=999)
    target_price_minor: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=2000)


class CardRequestOut(BaseModel):
    id: uuid.UUID
    public_ref: str
    status: str
    card_id: uuid.UUID | None = None
    requested_name: str
    set_code: str
    collector_number: str
    finish: str
    condition: str
    language: str
    quantity: int
    target_price: Money | None = None
    quote_price: Money | None = None
    quote_expires_at: datetime | None = None
    vendor_note: str
    customer_name: str
    reservation_id: uuid.UUID | None = None
    reservation_ref: str | None = None
    created_at: datetime
    updated_at: datetime
    access_token: str | None = None


class MeCardRequestOut(CardRequestOut):
    shop: dict


class MeCardRequestListOut(BaseModel):
    items: list[MeCardRequestOut]


class StaffCardRequestOut(CardRequestOut):
    customer_email: EmailStr
    customer_phone: str
    customer_note: str


class QuoteIn(BaseModel):
    quote_price_minor: int = Field(ge=0)
    quote_expires_at: datetime | None = None
    vendor_note: str = Field(default="", max_length=2000)


class DeclineIn(BaseModel):
    vendor_note: str = Field(default="", max_length=2000)


class ConvertIn(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=999)


class StaffUserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime


class StaffUserCreateIn(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    role: Literal["staff", "owner"] = "staff"


class StaffUserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=10, max_length=200)
    role: Literal["staff", "owner"] | None = None
    is_active: bool | None = None


class AuditEventOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: str
    summary: str
    actor_id: uuid.UUID | None = None
    actor_email: EmailStr | None = None
    data: dict
    created_at: datetime


class StockImportErrorOut(BaseModel):
    row: int
    message: str
    field: str | None = None


class ExchangeRateOut(BaseModel):
    source_currency: str
    target_currency: str
    rate: str
    rate_date: str


class StockImportReportOut(BaseModel):
    dry_run: bool
    rows: int
    created: int
    updated: int
    unchanged: int
    errors: list[StockImportErrorOut]
    exchange_rates: list[ExchangeRateOut]


class StockImportPricingIn(BaseModel):
    threshold_minor: int = Field(ge=0, le=2_147_483_647)
    fixed_price_minor: int = Field(ge=0, le=2_147_483_647)
    markup_percent: int = Field(ge=0, le=10000)


class StockImportPricingOut(BaseModel):
    currency: str
    configured: bool
    threshold_minor: int | None = None
    fixed_price_minor: int | None = None
    markup_percent: int | None = None


class DashboardOut(BaseModel):
    pending_reservations: int
    active_reservations: int
    open_requests: int = 0
    today_sales_minor: int
    currency: str
    low_stock: int
    stale_stock: int


class SettingsUpdateIn(BaseModel):
    brand_name: str | None = Field(default=None, max_length=200)
    logo_url: str | None = None
    colors: dict | None = None
    hero: dict | None = None
    contact: dict | None = None
    hours: dict | None = None
    payment_instructions: str | None = Field(default=None, max_length=4000)
    hold_hours: int | None = Field(default=None, ge=1, le=720)
    allow_backorders: bool | None = None
    directory_opt_in: bool | None = None
    notification_email: EmailStr | None = None
    scryfall_pricing_enabled: bool | None = None
    scryfall_min_price_minor: int | None = Field(default=None, ge=0, le=2_147_483_647)
    scryfall_markup_percent: int | None = Field(default=None, ge=0, le=10_000)
    scryfall_rounding_increment: int | None = Field(default=None, ge=1, le=21_474_836)
    archive_retention_days: int | None = Field(default=None, ge=0, le=3650)


class ScryfallRefreshOut(BaseModel):
    """Result of an owner-triggered Scryfall price refresh and stock reprice."""

    cards_refreshed: int
    cards_unavailable: int
    repriced_stock: int
    stock_without_scryfall_prices: int
