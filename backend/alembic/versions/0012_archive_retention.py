"""Archive retention setting and detachable stock history.

Revision ID: 0012_archive_retention
Revises: 0011_stock_archive
Create Date: 2026-11-09
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision = "0012_archive_retention"
down_revision = "0011_stock_archive"
branch_labels = None
depends_on = None

STOCK_FK = "fk_reservation_lines_stock_id_stock"
RETENTION_CHECK = "ck_settings_archive_retention_days"


def _stock_fk_name() -> str:
    """Find the existing stock foreign key on Postgres."""
    return op.get_bind().execute(
        text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'reservation_lines'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (stock_id) REFERENCES stock(id)%'
            """
        )
    ).scalar_one()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        # SQLite cannot add a CHECK or change a foreign key in place.
        with op.batch_alter_table("tenant_settings", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "archive_retention_days",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
            batch_op.create_check_constraint(
                RETENTION_CHECK,
                "archive_retention_days >= 0 AND archive_retention_days <= 3650",
            )
        with op.batch_alter_table(
            "reservation_lines",
            recreate="always",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch_op:
            batch_op.alter_column("stock_id", existing_type=sa.Uuid(), nullable=True)
            batch_op.drop_constraint(STOCK_FK, type_="foreignkey")
            batch_op.create_foreign_key(STOCK_FK, "stock", ["stock_id"], ["id"], ondelete="SET NULL")
    else:
        # Keep the existing table (and its RLS policies) on PostgreSQL.
        op.add_column(
            "tenant_settings",
            sa.Column("archive_retention_days", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_check_constraint(
            RETENTION_CHECK,
            "tenant_settings",
            "archive_retention_days >= 0 AND archive_retention_days <= 3650",
        )
        op.alter_column("reservation_lines", "stock_id", existing_type=sa.Uuid(), nullable=True)
        op.drop_constraint(_stock_fk_name(), "reservation_lines", type_="foreignkey")
        op.create_foreign_key(STOCK_FK, "reservation_lines", "stock", ["stock_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    # A downgrade cannot represent detached reservation lines. Terminal
    # reservations keep their denormalized line history, but lines whose stock
    # row was deleted must go before the column can be non-nullable again.
    op.execute("DELETE FROM reservation_lines WHERE stock_id IS NULL")

    if dialect == "sqlite":
        with op.batch_alter_table(
            "reservation_lines",
            recreate="always",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch_op:
            batch_op.drop_constraint(STOCK_FK, type_="foreignkey")
            batch_op.create_foreign_key(STOCK_FK, "stock", ["stock_id"], ["id"])
            batch_op.alter_column("stock_id", existing_type=sa.Uuid(), nullable=False)
        with op.batch_alter_table("tenant_settings", recreate="always") as batch_op:
            batch_op.drop_constraint(RETENTION_CHECK, type_="check")
            batch_op.drop_column("archive_retention_days")
    else:
        op.drop_constraint(STOCK_FK, "reservation_lines", type_="foreignkey")
        op.create_foreign_key(
            "reservation_lines_stock_id_fkey",
            "reservation_lines",
            "stock",
            ["stock_id"],
            ["id"],
        )
        op.alter_column("reservation_lines", "stock_id", existing_type=sa.Uuid(), nullable=False)
        op.drop_constraint(RETENTION_CHECK, "tenant_settings", type_="check")
        op.drop_column("tenant_settings", "archive_retention_days")
