"""SQLAlchemy models for the multi-tenant platform."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")
    locale: Mapped[str] = mapped_column(String(10), default="en")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Belgrade")
    plan_code: Mapped[str] = mapped_column(String(40), default="starter")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    settings: Mapped[TenantSettings | None] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", uselist=False
    )


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    brand_name: Mapped[str | None] = mapped_column(String(200))
    logo_url: Mapped[str | None] = mapped_column(Text)
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    hero: Mapped[dict] = mapped_column(JSON, default=dict)
    contact: Mapped[dict] = mapped_column(JSON, default=dict)
    hours: Mapped[dict] = mapped_column(JSON, default=dict)
    payment_instructions: Mapped[str] = mapped_column(Text, default="")
    hold_hours: Mapped[int] = mapped_column(Integer, default=24)
    allow_backorders: Mapped[bool] = mapped_column(Boolean, default=False)
    directory_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_email: Mapped[str | None] = mapped_column(String(320))
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="settings")

    __table_args__ = (CheckConstraint("hold_hours >= 1 AND hold_hours <= 720", name="ck_settings_hold_hours"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="customer")
    display_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        CheckConstraint("role IN ('platform_admin','owner','staff','customer')", name="ck_users_role"),
    )


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    game_code: Mapped[str] = mapped_column(String(20), default="mtg", index=True)
    provider: Mapped[str] = mapped_column(String(40), default="scryfall")
    provider_card_id: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(300), index=True)
    set_code: Mapped[str] = mapped_column(String(20), default="")
    set_name: Mapped[str] = mapped_column(String(200), default="")
    collector_number: Mapped[str] = mapped_column(String(40), default="")
    rarity: Mapped[str] = mapped_column(String(40), default="")
    type_line: Mapped[str] = mapped_column(String(300), default="")
    colors: Mapped[list] = mapped_column(JSON, default=list)
    image_small: Mapped[str | None] = mapped_column(Text)
    image_normal: Mapped[str | None] = mapped_column(Text)
    image_large: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("provider", "provider_card_id", name="uq_cards_provider_id"),
        Index("ix_cards_name_lower", "name"),
    )


class Stock(Base):
    __tablename__ = "stock"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cards.id"), index=True)
    finish: Mapped[str] = mapped_column(String(20), default="nonfoil")
    condition: Mapped[str] = mapped_column(String(10), default="NM")
    language: Mapped[str] = mapped_column(String(10), default="en")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    price_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    card: Mapped[Card] = relationship()

    @property
    def available(self) -> int:
        return max(0, self.quantity - self.reserved)

    __table_args__ = (
        UniqueConstraint("tenant_id", "card_id", "finish", "condition", "language", name="uq_stock_variant"),
        CheckConstraint("quantity >= 0", name="ck_stock_quantity"),
        CheckConstraint("reserved >= 0", name="ck_stock_reserved"),
        CheckConstraint("reserved <= quantity", name="ck_stock_reserved_le_quantity"),
        CheckConstraint("price_minor >= 0", name="ck_stock_price"),
        CheckConstraint("finish IN ('nonfoil','foil','etched')", name="ck_stock_finish"),
        CheckConstraint("condition IN ('NM','LP','MP','HP','DMG')", name="ck_stock_condition"),
        Index("ix_stock_tenant_card", "tenant_id", "card_id"),
    )


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    public_ref: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    customer_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str] = mapped_column(String(50), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    total_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(10), default="app")
    access_token_hash: Mapped[str | None] = mapped_column(String(64))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list[ReservationLine]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan", order_by="ReservationLine.name"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "public_ref", name="uq_reservations_ref"),
        CheckConstraint(
            "status IN ('REQUESTED','CONFIRMED','READY','COMPLETED','CANCELLED','EXPIRED')",
            name="ck_reservations_status",
        ),
        Index("ix_reservations_due", "status", "expires_at"),
        Index("ix_reservations_tenant_status", "tenant_id", "status", "created_at"),
    )


class ReservationLine(Base):
    __tablename__ = "reservation_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="CASCADE"), index=True
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stock.id"), index=True)
    card_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cards.id"))
    name: Mapped[str] = mapped_column(String(300))
    set_code: Mapped[str] = mapped_column(String(20), default="")
    collector_number: Mapped[str] = mapped_column(String(40), default="")
    finish: Mapped[str] = mapped_column(String(20))
    condition: Mapped[str] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    completed_quantity: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))

    reservation: Mapped[Reservation] = relationship(back_populates="lines")
    stock: Mapped[Stock] = relationship()

    @property
    def remaining(self) -> int:
        return self.quantity - self.completed_quantity - self.cancelled_quantity

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_lines_quantity"),
        CheckConstraint("completed_quantity >= 0", name="ck_lines_completed"),
        CheckConstraint("cancelled_quantity >= 0", name="ck_lines_cancelled"),
        CheckConstraint("completed_quantity + cancelled_quantity <= quantity", name="ck_lines_resolved"),
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    stock_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stock.id", ondelete="CASCADE"), index=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    on_hand_delta: Mapped[int] = mapped_column(Integer, default=0)
    reserved_delta: Mapped[int] = mapped_column(Integer, default=0)
    on_hand_after: Mapped[int] = mapped_column(Integer)
    reserved_after: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('RESERVE','RELEASE','SELL','SALE','ADJUST','IMPORT')",
            name="ck_movements_kind",
        ),
        Index("ix_movements_tenant_time", "tenant_id", "created_at"),
        Index("ix_movements_stock_time", "stock_id", "created_at"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    channel: Mapped[str] = mapped_column(String(20), default="in_app")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    endpoint: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
