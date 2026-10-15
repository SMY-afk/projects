"""create logistics shipping tables

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

from migrations.logistics_carrier_schema import create_carrier_tables
from migrations.logistics_package_schema import create_package_tables

revision: str = "8c9d0e1f2a3b"
down_revision: str | Sequence[str] | None = "7b8c9d0e1f2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_logistics_task_items_id_task_tenant",
        "logistics_task_items",
        ["id", "task_id", "tenant_id"],
    )
    create_package_tables(op)
    create_carrier_tables(op)


def downgrade() -> None:
    for table in (
        "logistics_waybills",
        "logistics_carrier_accounts",
        "logistics_carrier_services",
        "logistics_carriers",
        "logistics_package_items",
        "logistics_packages",
    ):
        op.drop_table(table)
    op.drop_constraint(
        "uq_logistics_task_items_id_task_tenant",
        "logistics_task_items",
        type_="unique",
    )
