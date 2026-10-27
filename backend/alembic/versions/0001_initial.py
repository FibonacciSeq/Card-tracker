"""Initial multi-tenant schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op
from app import models  # noqa: F401
from app.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# tenant_settings is deliberately excluded: the public shop directory must
# read branding/contact rows across tenants. It contains no customer data.
TENANT_TABLES = (
    "users",
    "stock",
    "reservations",
    "reservation_lines",
    "stock_movements",
    "notifications",
    "idempotency_keys",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f"""
                CREATE POLICY "{table}_tenant_isolation"
                ON "{table}"
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in reversed(TENANT_TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    Base.metadata.drop_all(bind=bind)
