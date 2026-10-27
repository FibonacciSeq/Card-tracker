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
    stock_id: uuid.UUID
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


class ReservationSummaryOut(BaseModel):
    id: uuid.UUID
    public_ref: str
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
    price: Money
    is_online: bool
    updated_at: datetime


class StaffStockListOut(BaseModel):
    items: list[StaffStockOut]


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


class DashboardOut(BaseModel):
    pending_reservations: int
    active_reservations: int
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
