"""Archive stock rows without breaking reservation history.

Revision ID: 0011_stock_archive
Revises: 0010_scryfall_stock_pricing
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_stock_archive"
down_revision = "0010_scryfall_stock_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_stock_tenant_archived", "stock", ["tenant_id", "archived_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_tenant_archived", table_name="stock")
    op.drop_column("stock", "archived_at")
