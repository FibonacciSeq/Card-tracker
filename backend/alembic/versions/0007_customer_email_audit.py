"""Customer email changes and global account audit events.

Revision ID: 0007_customer_email_audit
Revises: 0006_customer_notification_preferences
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_customer_email_audit"
down_revision = "0006_customer_notification_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_otp_challenges", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_index("ix_otp_user_created", "customer_otp_challenges", ["user_id", "created_at"])

    op.create_table(
        "customer_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_customer_audit_events_user_id", "customer_audit_events", ["user_id"])
    op.create_index("ix_customer_audit_events_action", "customer_audit_events", ["action"])
    op.create_index("ix_customer_audit_events_created_at", "customer_audit_events", ["created_at"])
    op.create_index(
        "ix_customer_audit_events_user_created",
        "customer_audit_events",
        ["user_id", "created_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "customer_audit_events" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "customer_audit_events" FORCE ROW LEVEL SECURITY')
        op.execute(
            """
            CREATE POLICY "customer_audit_events_customer_own"
            ON customer_audit_events
            USING (
                user_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
            )
            WITH CHECK (
                user_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('DROP POLICY IF EXISTS "customer_audit_events_customer_own" ON customer_audit_events')

    op.drop_index("ix_customer_audit_events_user_created", table_name="customer_audit_events")
    op.drop_index("ix_customer_audit_events_created_at", table_name="customer_audit_events")
    op.drop_index("ix_customer_audit_events_action", table_name="customer_audit_events")
    op.drop_index("ix_customer_audit_events_user_id", table_name="customer_audit_events")
    op.drop_table("customer_audit_events")

    op.drop_index("ix_otp_user_created", table_name="customer_otp_challenges")
    op.drop_column("customer_otp_challenges", "user_id")
