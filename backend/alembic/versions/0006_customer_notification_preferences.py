"""Customer notification preferences for account settings.

Revision ID: 0006_customer_notification_preferences
Revises: 0005_push_tokens
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_customer_notification_preferences"
down_revision = "0005_push_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("push_notifications_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column(
        "users", sa.Column("email_notifications_enabled", sa.Boolean(), nullable=False, server_default="true")
    )
    op.add_column("users", sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("notifications_opt_out", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "notifications_opt_out")
    op.drop_column("users", "quiet_hours_enabled")
    op.drop_column("users", "email_notifications_enabled")
    op.drop_column("users", "push_notifications_enabled")
