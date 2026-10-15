"""add logistics optimistic lock versions

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d0e1f2a3b4c"
down_revision: str | Sequence[str] | None = "8c9d0e1f2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONED_TABLES = (
    "logistics_tasks",
    "logistics_packages",
    "logistics_carriers",
    "logistics_carrier_services",
    "logistics_carrier_accounts",
    "logistics_waybills",
)


def upgrade() -> None:
    for table in VERSIONED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "version_id",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            ),
        )
    op.create_unique_constraint(
        "uq_logistics_waybills_id_tenant",
        "logistics_waybills",
        ["id", "tenant_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_logistics_waybills_id_tenant",
        "logistics_waybills",
        type_="unique",
    )
    for table in reversed(VERSIONED_TABLES):
        op.drop_column(table, "version_id")
