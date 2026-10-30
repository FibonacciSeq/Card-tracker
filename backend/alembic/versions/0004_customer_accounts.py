"""Customer accounts, OTP challenges, and cross-tenant account rows.

Revision ID: 0004_customer_accounts
Revises: 0003_requests_alerts
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_customer_accounts"
down_revision = "0003_requests_alerts"
branch_labels = None
depends_on = None

CUSTOMER_TABLES = ("reservations", "card_requests", "restock_alerts")


def upgrade() -> None:
    op.create_table(
        "customer_otp_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("email_sent_at", sa.DateTime(timezone=True)),
        sa.Column("email_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_email_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("email_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_otp_challenges_email",
        "customer_otp_challenges",
        ["email"],
    )
    op.create_index(
        "ix_otp_email_created",
        "customer_otp_challenges",
        ["email", "created_at"],
    )
    op.create_index(
        "ix_otp_pending_email",
        "customer_otp_challenges",
        ["email_sent_at", "next_email_attempt_at"],
    )
    op.create_index("ix_otp_expires", "customer_otp_challenges", ["expires_at"])

    op.execute(
        "CREATE UNIQUE INDEX uq_users_customer_global_email "
        "ON users (lower(email)) "
        "WHERE role = 'customer' AND tenant_id IS NULL"
    )
    op.create_index("ix_reservations_customer", "reservations", ["customer_id", "created_at"])
    op.create_index("ix_card_requests_customer", "card_requests", ["customer_id", "created_at"])
    op.create_index("ix_restock_alerts_customer", "restock_alerts", ["customer_id", "created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Permissive policies are OR-ed with the existing tenant policies.
        op.execute(
            """
            CREATE POLICY "users_global_customer"
            ON users
            USING (tenant_id IS NULL AND role = 'customer')
            WITH CHECK (tenant_id IS NULL AND role = 'customer')
            """
        )
        for table in CUSTOMER_TABLES:
            op.execute(
                f"""
                CREATE POLICY "{table}_customer_own"
                ON "{table}"
                USING (
                    customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
                )
                WITH CHECK (
                    customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
                )
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in reversed(CUSTOMER_TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{table}_customer_own" ON "{table}"')
        op.execute('DROP POLICY IF EXISTS "users_global_customer" ON "users"')

    op.drop_index("ix_restock_alerts_customer", table_name="restock_alerts")
    op.drop_index("ix_card_requests_customer", table_name="card_requests")
    op.drop_index("ix_reservations_customer", table_name="reservations")
    op.execute("DROP INDEX IF EXISTS uq_users_customer_global_email")

    op.drop_index("ix_otp_expires", table_name="customer_otp_challenges")
    op.drop_index("ix_otp_pending_email", table_name="customer_otp_challenges")
    op.drop_index("ix_otp_email_created", table_name="customer_otp_challenges")
    op.drop_index("ix_customer_otp_challenges_email", table_name="customer_otp_challenges")
    op.drop_table("customer_otp_challenges")
