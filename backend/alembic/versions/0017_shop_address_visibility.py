"""Require a shop address for owners and allow customers to see it.

Revision ID: 0017_shop_address_visibility
Revises: 0016_remove_shop_location
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017_shop_address_visibility"
down_revision = "0016_remove_shop_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch_op:
        batch_op.add_column(sa.Column("address", sa.String(length=300), nullable=True))
        batch_op.add_column(
            sa.Column(
                "show_address",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch_op:
        batch_op.drop_column("show_address")
        batch_op.drop_column("address")
