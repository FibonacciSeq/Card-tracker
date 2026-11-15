"""Add optional shop coordinates for the customer radius search.

Revision ID: 0015_shop_location
Revises: 0014_customer_auth_purposes
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_shop_location"
down_revision = "0014_customer_auth_purposes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch_op:
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        batch_op.create_check_constraint(
            "ck_settings_latitude",
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
        )
        batch_op.create_check_constraint(
            "ck_settings_longitude",
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch_op:
        batch_op.drop_constraint("ck_settings_longitude", type_="check")
        batch_op.drop_constraint("ck_settings_latitude", type_="check")
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")
