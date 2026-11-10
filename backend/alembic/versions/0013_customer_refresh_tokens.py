"""Customer refresh tokens for session renewal without a new OTP.

Revision ID: 0013_customer_refresh_tokens
Revises: 0012_archive_retention
Create Date: 2026-11-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_customer_refresh_tokens"
down_revision = "0012_archive_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_by", sa.Uuid()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["replaced_by"], ["customer_refresh_tokens.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_refresh_tokens_user_id", "customer_refresh_tokens", ["user_id"])
    op.create_index(
        "ix_customer_refresh_tokens_token_hash",
        "customer_refresh_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_customer_refresh_tokens_replaced_by", "customer_refresh_tokens", ["replaced_by"]
    )
    op.create_index(
        "ix_customer_refresh_tokens_user_active",
        "customer_refresh_tokens",
        ["user_id", "revoked_at"],
    )

    # No row-level security, like customer_otp_challenges: the table holds only
    # one-way token hashes and rows are reached pre-authentication by exact
    # token hash (the refresh token itself is the credential), so a
    # customer-scoped policy would break /v1/auth/refresh.


def downgrade() -> None:
    op.drop_index("ix_customer_refresh_tokens_user_active", table_name="customer_refresh_tokens")
    op.drop_index(
        "ix_customer_refresh_tokens_replaced_by", table_name="customer_refresh_tokens"
    )
    op.drop_index(
        "ix_customer_refresh_tokens_token_hash", table_name="customer_refresh_tokens"
    )
    op.drop_index("ix_customer_refresh_tokens_user_id", table_name="customer_refresh_tokens")
    op.drop_table("customer_refresh_tokens")
