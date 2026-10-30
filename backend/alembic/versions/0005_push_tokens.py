"""Native APNs/FCM device tokens for customer accounts.

Revision ID: 0005_push_tokens
Revises: 0004_customer_accounts
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_push_tokens"
down_revision = "0004_customer_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("platform IN ('ios','android')", name="ck_push_tokens_platform"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_push_tokens_hash"),
    )
    op.create_index("ix_push_tokens_user_id", "push_tokens", ["user_id"])
    op.create_index("ix_push_tokens_user_active", "push_tokens", ["user_id", "revoked_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE POLICY "push_tokens_customer_own"
            ON push_tokens
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
        op.execute('DROP POLICY IF EXISTS "push_tokens_customer_own" ON push_tokens')

    op.drop_index("ix_push_tokens_user_active", table_name="push_tokens")
    op.drop_index("ix_push_tokens_user_id", table_name="push_tokens")
    op.drop_table("push_tokens")
