"""Initial multi-tenant schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-27

The baseline is written out explicitly rather than built from the live models.
Migrations are history: if this file consulted `Base.metadata`, every later
model change would leak into fresh installs and collide with the migration that
introduces it (for example, `is_active` in 0002).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# tenant_settings is deliberately excluded: the public shop directory must
# read branding/contact rows across tenants. It contains no customer data.
TENANT_TABLES = (
    "users",
    "stock",
    "reservations",
    "reservation_lines",
    "stock_movements",
    "notifications",
    "idempotency_keys",
)


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_code", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_card_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("set_code", sa.String(length=20), nullable=False),
        sa.Column("set_name", sa.String(length=200), nullable=False),
        sa.Column("collector_number", sa.String(length=40), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("type_line", sa.String(length=300), nullable=False),
        sa.Column("colors", sa.JSON(), nullable=False),
        sa.Column("image_small", sa.Text()),
        sa.Column("image_normal", sa.Text()),
        sa.Column("image_large", sa.Text()),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_card_id", name="uq_cards_provider_id"),
    )
    op.create_index("ix_cards_game_code", "cards", ["game_code"])
    op.create_index("ix_cards_name", "cards", ["name"])
    op.create_index("ix_cards_name_lower", "cards", ["name"])

    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid()),
        sa.Column("endpoint", sa.String(length=120), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid()),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("plan_code", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "stock",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("card_id", sa.Uuid(), sa.ForeignKey("cards.id"), nullable=False),
        sa.Column("finish", sa.String(length=20), nullable=False),
        sa.Column("condition", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("reserved <= quantity", name="ck_stock_reserved_le_quantity"),
        sa.CheckConstraint("condition IN ('NM','LP','MP','HP','DMG')", name="ck_stock_condition"),
        sa.CheckConstraint("price_minor >= 0", name="ck_stock_price"),
        sa.CheckConstraint("reserved >= 0", name="ck_stock_reserved"),
        sa.CheckConstraint("finish IN ('nonfoil','foil','etched')", name="ck_stock_finish"),
        sa.CheckConstraint("quantity >= 0", name="ck_stock_quantity"),
        sa.UniqueConstraint("tenant_id", "card_id", "finish", "condition", "language", name="uq_stock_variant"),
    )
    op.create_index("ix_stock_card_id", "stock", ["card_id"])
    op.create_index("ix_stock_tenant_card", "stock", ["tenant_id", "card_id"])
    op.create_index("ix_stock_tenant_id", "stock", ["tenant_id"])

    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("brand_name", sa.String(length=200)),
        sa.Column("logo_url", sa.Text()),
        sa.Column("colors", sa.JSON(), nullable=False),
        sa.Column("hero", sa.JSON(), nullable=False),
        sa.Column("contact", sa.JSON(), nullable=False),
        sa.Column("hours", sa.JSON(), nullable=False),
        sa.Column("payment_instructions", sa.Text(), nullable=False),
        sa.Column("hold_hours", sa.Integer(), nullable=False),
        sa.Column("allow_backorders", sa.Boolean(), nullable=False),
        sa.Column("directory_opt_in", sa.Boolean(), nullable=False),
        sa.Column("notification_email", sa.String(length=320)),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.CheckConstraint("hold_hours >= 1 AND hold_hours <= 720", name="ck_settings_hold_hours"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE")),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=200)),
        sa.Column("phone", sa.String(length=50)),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("role IN ('platform_admin','owner','staff','customer')", name="ck_users_role"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_ref", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("access_token_hash", sa.String(length=64)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('REQUESTED','CONFIRMED','READY','COMPLETED','CANCELLED','EXPIRED')",
            name="ck_reservations_status",
        ),
        sa.UniqueConstraint("tenant_id", "public_ref", name="uq_reservations_ref"),
    )
    op.create_index("ix_reservations_due", "reservations", ["status", "expires_at"])
    op.create_index("ix_reservations_tenant_id", "reservations", ["tenant_id"])
    op.create_index("ix_reservations_tenant_status", "reservations", ["tenant_id", "status", "created_at"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stock_id", sa.Uuid(), sa.ForeignKey("stock.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reservation_id", sa.Uuid()),
        sa.Column("line_id", sa.Uuid()),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("on_hand_delta", sa.Integer(), nullable=False),
        sa.Column("reserved_delta", sa.Integer(), nullable=False),
        sa.Column("on_hand_after", sa.Integer(), nullable=False),
        sa.Column("reserved_after", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('RESERVE','RELEASE','SELL','SALE','ADJUST','IMPORT')", name="ck_movements_kind"),
    )
    op.create_index("ix_movements_stock_time", "stock_movements", ["stock_id", "created_at"])
    op.create_index("ix_movements_tenant_time", "stock_movements", ["tenant_id", "created_at"])
    op.create_index("ix_stock_movements_stock_id", "stock_movements", ["stock_id"])
    op.create_index("ix_stock_movements_tenant_id", "stock_movements", ["tenant_id"])

    op.create_table(
        "reservation_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stock_id", sa.Uuid(), sa.ForeignKey("stock.id"), nullable=False),
        sa.Column("card_id", sa.Uuid(), sa.ForeignKey("cards.id"), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("set_code", sa.String(length=20), nullable=False),
        sa.Column("collector_number", sa.String(length=40), nullable=False),
        sa.Column("finish", sa.String(length=20), nullable=False),
        sa.Column("condition", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("completed_quantity", sa.Integer(), nullable=False),
        sa.Column("cancelled_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("cancelled_quantity >= 0", name="ck_lines_cancelled"),
        sa.CheckConstraint("quantity > 0", name="ck_lines_quantity"),
        sa.CheckConstraint("completed_quantity + cancelled_quantity <= quantity", name="ck_lines_resolved"),
        sa.CheckConstraint("completed_quantity >= 0", name="ck_lines_completed"),
    )
    op.create_index("ix_reservation_lines_reservation_id", "reservation_lines", ["reservation_id"])
    op.create_index("ix_reservation_lines_stock_id", "reservation_lines", ["stock_id"])
    op.create_index("ix_reservation_lines_tenant_id", "reservation_lines", ["tenant_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f"""
                CREATE POLICY "{table}_tenant_isolation"
                ON "{table}"
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in reversed(TENANT_TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("reservation_lines")
    op.drop_table("stock_movements")
    op.drop_table("reservations")
    op.drop_table("users")
    op.drop_table("tenant_settings")
    op.drop_table("stock")
    op.drop_table("tenants")
    op.drop_table("notifications")
    op.drop_table("idempotency_keys")
    op.drop_table("cards")
