"""add logistics task quantities

Revision ID: bf2a3b4c5d6e
Revises: ae1f2a3b4c5d
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bf2a3b4c5d6e"
down_revision: str | Sequence[str] | None = "ae1f2a3b4c5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_logistics_task_items_quantity",
        "logistics_task_items",
        type_="check",
    )
    op.alter_column(
        "logistics_task_items", "quantity", new_column_name="planned_quantity"
    )
    for column_name in ("packed_quantity", "shipped_quantity"):
        op.add_column(
            "logistics_task_items",
            sa.Column(
                column_name,
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    op.execute(
        sa.text(
            """
            WITH package_progress AS (
                SELECT
                    item.task_item_id,
                    item.tenant_id,
                    SUM(CASE WHEN package.status != 'cancelled' THEN item.quantity ELSE 0 END) AS packed,
                    SUM(CASE WHEN package.status = 'shipped' THEN item.quantity ELSE 0 END) AS shipped
                FROM logistics_package_items AS item
                JOIN logistics_packages AS package
                  ON package.id = item.package_id
                 AND package.task_id = item.task_id
                 AND package.tenant_id = item.tenant_id
                GROUP BY item.task_item_id, item.tenant_id
            )
            UPDATE logistics_task_items AS task_item
            SET packed_quantity = LEAST(task_item.planned_quantity, progress.packed),
                shipped_quantity = LEAST(task_item.planned_quantity, progress.shipped)
            FROM package_progress AS progress
            WHERE task_item.id = progress.task_item_id
              AND task_item.tenant_id = progress.tenant_id
            """
        )
    )
    op.create_check_constraint(
        "ck_logistics_task_items_planned_quantity",
        "logistics_task_items",
        "planned_quantity > 0",
    )
    op.create_check_constraint(
        "ck_logistics_task_items_quantity_progress",
        "logistics_task_items",
        "shipped_quantity >= 0 AND shipped_quantity <= packed_quantity "
        "AND packed_quantity <= planned_quantity",
    )


def downgrade() -> None:
    for constraint_name in (
        "ck_logistics_task_items_quantity_progress",
        "ck_logistics_task_items_planned_quantity",
    ):
        op.drop_constraint(constraint_name, "logistics_task_items", type_="check")
    op.drop_column("logistics_task_items", "shipped_quantity")
    op.drop_column("logistics_task_items", "packed_quantity")
    op.alter_column(
        "logistics_task_items", "planned_quantity", new_column_name="quantity"
    )
    op.create_check_constraint(
        "ck_logistics_task_items_quantity",
        "logistics_task_items",
        "quantity > 0",
    )
