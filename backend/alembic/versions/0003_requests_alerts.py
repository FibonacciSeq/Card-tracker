"""Special orders, restock alerts, and notification delivery state.

Revision ID: 0003_requests_alerts
Revises: 0002_audit
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_requests_alerts"
down_revision = "0002_audit"
branch_labels = None
depends_on = None

TENANT_TABLES = ("card_requests", "restock_alerts")


def upgrade() -> None:
    op.create_table(
        "card_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_ref", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("card_id", sa.Uuid(), sa.ForeignKey("cards.id")),
        sa.Column("requested_name", sa.String(length=300), nullable=False),
        sa.Column("set_code", sa.String(length=20), nullable=False),
        sa.Column("collector_number", sa.String(length=40), nullable=False),
        sa.Column("finish", sa.String(length=20), nullable=False),
        sa.Column("condition", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("target_price_minor", sa.Integer()),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("customer_note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("quote_price_minor", sa.Integer()),
        sa.Column("quote_currency", sa.String(length=3)),
        sa.Column("quote_expires_at", sa.DateTime(timezone=True)),
        sa.Column("vendor_note", sa.Text(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id", ondelete="SET NULL")),
        sa.Column("access_token_hash", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "public_ref", name="uq_card_requests_ref"),
        sa.CheckConstraint("quantity > 0", name="ck_card_requests_quantity"),
        sa.CheckConstraint(
            "status IN ('REQUESTED','QUOTED','ACCEPTED','DECLINED','EXPIRED','CONVERTED','CANCELLED')",
            name="ck_card_requests_status",
        ),
    )
    op.create_index("ix_card_requests_tenant_id", "card_requests", ["tenant_id"])
    op.create_index("ix_card_requests_queue", "card_requests", ["tenant_id", "status", "created_at"])

    op.create_table(
        "restock_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("customer_name", sa.String(length=200)),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("card_id", sa.Uuid(), sa.ForeignKey("cards.id"), nullable=False),
        sa.Column("stock_id", sa.Uuid(), sa.ForeignKey("stock.id", ondelete="SET NULL")),
        sa.Column("finish", sa.String(length=20), nullable=False),
        sa.Column("condition", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "email",
            "card_id",
            "finish",
            "condition",
            "language",
            name="uq_restock_alerts_subscription",
        ),
    )
    op.create_index("ix_restock_alerts_tenant_id", "restock_alerts", ["tenant_id"])
    op.create_index("ix_restock_alerts_card_id", "restock_alerts", ["card_id"])
    op.create_index(
        "ix_restock_alerts_variant",
        "restock_alerts",
        ["tenant_id", "card_id", "finish", "condition", "language"],
    )

    op.add_column("notifications", sa.Column("recipient", sa.String(length=320)))
    op.add_column(
        "notifications",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.create_index("ix_notifications_pending", "notifications", ["sent_at", "next_attempt_at"])

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

    op.drop_index("ix_notifications_pending", table_name="notifications")
    op.drop_column("notifications", "next_attempt_at")
    op.drop_column("notifications", "attempts")
    op.drop_column("notifications", "recipient")

    op.drop_index("ix_restock_alerts_variant", table_name="restock_alerts")
    op.drop_index("ix_restock_alerts_card_id", table_name="restock_alerts")
    op.drop_index("ix_restock_alerts_tenant_id", table_name="restock_alerts")
    op.drop_table("restock_alerts")

    op.drop_index("ix_card_requests_queue", table_name="card_requests")
    op.drop_index("ix_card_requests_tenant_id", table_name="card_requests")
    op.drop_table("card_requests")
