"""Scope customer OTP challenges to a sign-in, signup, reset, or email change.

Revision ID: 0014_customer_auth_purposes
Revises: 0013_customer_refresh_tokens
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_customer_auth_purposes"
down_revision = "0013_customer_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_otp_challenges",
        sa.Column("purpose", sa.String(length=20), nullable=False, server_default="login"),
    )
    op.create_index(
        "ix_otp_email_purpose_created",
        "customer_otp_challenges",
        ["email", "purpose", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_otp_email_purpose_created", table_name="customer_otp_challenges")
    op.drop_column("customer_otp_challenges", "purpose")
