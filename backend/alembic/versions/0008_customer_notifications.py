"""Customer notification delivery log and push-token diagnostics.

Revision ID: 0008_customer_notifications
Revises: 0007_customer_email_audit
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_customer_notifications"
down_revision = "0007_customer_email_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "push_tokens",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "push_tokens",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "push_tokens",
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_notifications_user_id_id",
        "notifications",
        ["user_id", "id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE POLICY "notifications_customer_own"
            ON notifications
            FOR SELECT
            USING (
                user_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('DROP POLICY IF EXISTS "notifications_customer_own" ON notifications')

    op.drop_index("ix_notifications_user_id_id", table_name="notifications")

    op.drop_column("push_tokens", "last_error")
    op.drop_column("push_tokens", "last_failure_at")
    op.drop_column("push_tokens", "failure_count")
