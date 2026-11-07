"""Persist shop-wide stock import pricing rules.

Revision ID: 0009_stock_import_pricing
Revises: 0008_customer_notifications
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_stock_import_pricing"
down_revision = "0008_customer_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_settings", sa.Column("stock_import_pricing", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_settings", "stock_import_pricing")
