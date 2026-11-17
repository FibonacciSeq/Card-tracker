"""Use the contact address instead of a separate shop address field.

Revision ID: 0018_drop_shop_address
Revises: 0017_shop_address_visibility
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018_drop_shop_address"
down_revision = "0017_shop_address_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch_op:
        batch_op.drop_column("address")


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch_op:
        batch_op.add_column(sa.Column("address", sa.String(length=300), nullable=True))
