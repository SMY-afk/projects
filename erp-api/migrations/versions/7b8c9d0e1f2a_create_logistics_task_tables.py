"""create logistics task tables

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b8c9d0e1f2a"
down_revision: str | Sequence[str] | None = "6a7b8c9d0e1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def _task_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["task_id", "tenant_id"],
        ["logistics_tasks.id", "logistics_tasks.tenant_id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    _create_tasks()
    _create_items()
    _create_operations()
    _create_reviews()


def _create_tasks() -> None:
    op.create_table(
        "logistics_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_number", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_reference_id", sa.Uuid(), nullable=False),
        sa.Column("source_number", sa.String(128), nullable=False),
        sa.Column("order_id", sa.Uuid()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source_type IN ('sales_order', 'exchange')",
            name="ck_logistics_tasks_source_type",
        ),
        sa.CheckConstraint(
            "(source_type = 'sales_order' AND order_id IS NOT NULL AND source_reference_id = order_id) "
            "OR (source_type = 'exchange' AND order_id IS NULL)",
            name="ck_logistics_tasks_source_link",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'reviewed', 'review_exception', "
            "'ready_to_ship', 'shipped', 'cancelled')",
            name="ck_logistics_tasks_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_logistics_tasks_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "task_number", name="uq_logistics_tasks_tenant_number"
        ),
    )
    op.create_index("ix_logistics_tasks_tenant_id", "logistics_tasks", ["tenant_id"])
    op.create_index(
        "ix_logistics_tasks_filter",
        "logistics_tasks",
        ["tenant_id", "status", "source_type", "created_at"],
    )


def _create_items() -> None:
    op.create_table(
        "logistics_task_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("source_line_id", sa.Uuid(), nullable=False),
        sa.Column("order_line_id", sa.Uuid()),
        sa.Column("platform_product_id", sa.String(128)),
        sa.Column("platform_sku_id", sa.String(128)),
        sa.Column("seller_sku", sa.String(128)),
        sa.Column("product_name", sa.String(300), nullable=False),
        sa.Column("sku_name", sa.String(300)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _task_fk(),
        sa.ForeignKeyConstraint(
            ["order_line_id", "tenant_id"],
            ["order_lines.id", "order_lines.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_logistics_task_items_quantity"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "task_id",
            "source_line_id",
            name="uq_logistics_task_items_tenant_task_source_line",
        ),
    )
    op.create_index(
        "ix_logistics_task_items_tenant_id", "logistics_task_items", ["tenant_id"]
    )
    op.create_index(
        "ix_logistics_task_items_task_id", "logistics_task_items", ["task_id"]
    )


def _create_operations() -> None:
    op.create_table(
        "logistics_task_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32)),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _task_fk(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_logistics_task_operations_tenant_id",
        "logistics_task_operations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_logistics_task_operations_task_id", "logistics_task_operations", ["task_id"]
    )
    op.create_index(
        "ix_logistics_task_operations_actor_user_id",
        "logistics_task_operations",
        ["actor_user_id"],
    )


def _create_reviews() -> None:
    op.create_table(
        "logistics_task_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("expected_quantity", sa.Integer(), nullable=False),
        sa.Column("actual_quantity", sa.Integer(), nullable=False),
        sa.Column(
            "differences",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("note", sa.Text()),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _task_fk(),
        sa.CheckConstraint(
            "result IN ('passed', 'difference', 'damaged', 'quantity_mismatch')",
            name="ck_logistics_task_reviews_result",
        ),
        sa.CheckConstraint(
            "expected_quantity >= 0 AND actual_quantity >= 0",
            name="ck_logistics_task_reviews_quantities",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_logistics_task_reviews_tenant_id", "logistics_task_reviews", ["tenant_id"]
    )
    op.create_index(
        "ix_logistics_task_reviews_task_id", "logistics_task_reviews", ["task_id"]
    )
    op.create_index(
        "ix_logistics_task_reviews_reviewer_user_id",
        "logistics_task_reviews",
        ["reviewer_user_id"],
    )


def downgrade() -> None:
    for table in (
        "logistics_task_reviews",
        "logistics_task_operations",
        "logistics_task_items",
        "logistics_tasks",
    ):
        op.drop_table(table)
