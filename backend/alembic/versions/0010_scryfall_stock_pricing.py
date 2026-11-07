"""Store Scryfall market prices and shop catalog-pricing settings.

Revision ID: 0010_scryfall_stock_pricing
Revises: 0009_stock_import_pricing
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_scryfall_stock_pricing"
down_revision = "0009_stock_import_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("scryfall_prices", sa.JSON(), nullable=True))
    op.add_column("tenant_settings", sa.Column("scryfall_pricing", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_settings", "scryfall_pricing")
    op.drop_column("cards", "scryfall_prices")
