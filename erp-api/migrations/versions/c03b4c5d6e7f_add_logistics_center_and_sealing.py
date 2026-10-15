"""add logistics task filters and package sealing audit"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c03b4c5d6e7f"
down_revision: str | Sequence[str] | None = "bf2a3b4c5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("logistics_tasks", sa.Column("shop_id", sa.Uuid(), nullable=True))
    op.add_column(
        "logistics_tasks",
        sa.Column(
            "priority",
            sa.String(length=16),
            nullable=False,
            server_default="normal",
        ),
    )
    op.execute(
        """
        UPDATE logistics_tasks AS task
        SET shop_id = orders.shop_id
        FROM orders
        WHERE task.order_id = orders.id
          AND task.tenant_id = orders.tenant_id
        """
    )
    op.create_foreign_key(
        "fk_logistics_tasks_shop_tenant",
        "logistics_tasks",
        "shops",
        ["shop_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_logistics_tasks_priority",
        "logistics_tasks",
        "priority IN ('low', 'normal', 'high', 'urgent')",
    )
    op.create_index(
        "ix_logistics_tasks_center_filter",
        "logistics_tasks",
        ["tenant_id", "shop_id", "source_type", "status", "priority", "created_at"],
    )
    op.add_column(
        "logistics_packages", sa.Column("sealed_by_user_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "logistics_packages",
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE logistics_packages
        SET sealed_by_user_id = created_by_user_id,
            sealed_at = created_at
        WHERE status <> 'draft'
        """
    )
    op.create_check_constraint(
        "ck_logistics_packages_sealing_audit",
        "logistics_packages",
        "(sealed_by_user_id IS NULL) = (sealed_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_logistics_packages_sealing_audit",
        "logistics_packages",
        type_="check",
    )
    op.drop_column("logistics_packages", "sealed_at")
    op.drop_column("logistics_packages", "sealed_by_user_id")
    op.drop_index("ix_logistics_tasks_center_filter", table_name="logistics_tasks")
    op.drop_constraint("ck_logistics_tasks_priority", "logistics_tasks", type_="check")
    op.drop_constraint(
        "fk_logistics_tasks_shop_tenant", "logistics_tasks", type_="foreignkey"
    )
    op.drop_column("logistics_tasks", "priority")
    op.drop_column("logistics_tasks", "shop_id")
