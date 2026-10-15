"""Create returns, RMA, and reverse logistics links.

Revision ID: b1c2d3e4f5a6
Revises: a0de2f4567b9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0de2f4567b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_return_requests()
    _create_return_request_items()
    _create_return_rmas()
    _extend_logistics_tasks()


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM logistics_tasks WHERE direction = 'reverse'"))
    op.drop_constraint(
        "fk_logistics_tasks_return_rma_tenant", "logistics_tasks", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_logistics_tasks_tenant_rma", "logistics_tasks", type_="unique"
    )
    op.drop_constraint(
        "ck_logistics_tasks_source_link", "logistics_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_logistics_tasks_source_type", "logistics_tasks", type_="check"
    )
    op.drop_constraint("ck_logistics_tasks_direction", "logistics_tasks", type_="check")
    op.drop_column("logistics_tasks", "return_rma_id")
    op.drop_column("logistics_tasks", "direction")
    op.create_check_constraint(
        "ck_logistics_tasks_source_type",
        "logistics_tasks",
        "source_type IN ('sales_order', 'exchange')",
    )
    op.create_check_constraint(
        "ck_logistics_tasks_source_link",
        "logistics_tasks",
        "(source_type = 'sales_order' AND order_id IS NOT NULL "
        "AND source_reference_id = order_id) OR "
        "(source_type = 'exchange' AND order_id IS NULL)",
    )
    op.drop_table("return_rmas")
    op.drop_table("return_request_items")
    op.drop_table("return_requests")


def _create_return_requests() -> None:
    op.create_table(
        "return_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("request_number", sa.String(40), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("request_type", sa.String(16), nullable=False),
        sa.Column(
            "status", sa.String(24), nullable=False, server_default="pending_review"
        ),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("customer_note", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid()),
        sa.Column("review_note", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_return_requests_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "request_number", name="uq_return_requests_tenant_number"
        ),
        sa.CheckConstraint(
            "request_type IN ('return', 'exchange')",
            name="ck_return_requests_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected', 'cancelled')",
            name="ck_return_requests_status",
        ),
        sa.CheckConstraint(
            "(reviewed_by_user_id IS NULL) = (reviewed_at IS NULL)",
            name="ck_return_requests_review_audit",
        ),
    )
    op.create_index(
        "ix_return_requests_center",
        "return_requests",
        ["tenant_id", "status", "request_type", "created_at"],
    )


def _create_return_request_items() -> None:
    op.create_table(
        "return_request_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("return_request_id", sa.Uuid(), nullable=False),
        sa.Column("order_line_id", sa.Uuid(), nullable=False),
        sa.Column("requested_quantity", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("note", sa.Text()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["return_request_id", "tenant_id"],
            ["return_requests.id", "return_requests.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id", "tenant_id"],
            ["order_lines.id", "order_lines.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_return_request_items_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "return_request_id",
            "order_line_id",
            name="uq_return_request_items_request_line",
        ),
        sa.CheckConstraint(
            "requested_quantity > 0", name="ck_return_request_items_quantity"
        ),
    )
    op.create_index(
        "ix_return_request_items_request",
        "return_request_items",
        ["return_request_id"],
    )
    op.create_index(
        "ix_return_request_items_order_line",
        "return_request_items",
        ["order_line_id"],
    )


def _create_return_rmas() -> None:
    op.create_table(
        "return_rmas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("return_request_id", sa.Uuid(), nullable=False),
        sa.Column("rma_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["return_request_id", "tenant_id"],
            ["return_requests.id", "return_requests.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_return_rmas_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "rma_number", name="uq_return_rmas_tenant_number"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "return_request_id",
            name="uq_return_rmas_tenant_request",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_transit', 'received', 'closed', 'cancelled')",
            name="ck_return_rmas_status",
        ),
    )
    op.create_index(
        "ix_return_rmas_return_request", "return_rmas", ["return_request_id"]
    )


def _extend_logistics_tasks() -> None:
    op.add_column(
        "logistics_tasks",
        sa.Column("direction", sa.String(16), nullable=False, server_default="forward"),
    )
    op.add_column("logistics_tasks", sa.Column("return_rma_id", sa.Uuid()))
    op.drop_constraint(
        "ck_logistics_tasks_source_link", "logistics_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_logistics_tasks_source_type", "logistics_tasks", type_="check"
    )
    op.create_check_constraint(
        "ck_logistics_tasks_direction",
        "logistics_tasks",
        "direction IN ('forward', 'reverse')",
    )
    op.create_check_constraint(
        "ck_logistics_tasks_source_type",
        "logistics_tasks",
        "source_type IN ('sales_order', 'return', 'exchange')",
    )
    op.create_check_constraint(
        "ck_logistics_tasks_source_link",
        "logistics_tasks",
        "(direction = 'forward' AND source_type = 'sales_order' "
        "AND order_id IS NOT NULL AND return_rma_id IS NULL "
        "AND source_reference_id = order_id) OR "
        "(direction = 'reverse' AND source_type IN ('return', 'exchange') "
        "AND order_id IS NOT NULL AND return_rma_id IS NOT NULL "
        "AND source_reference_id = return_rma_id)",
    )
    op.create_unique_constraint(
        "uq_logistics_tasks_tenant_rma",
        "logistics_tasks",
        ["tenant_id", "return_rma_id"],
    )
    op.create_foreign_key(
        "fk_logistics_tasks_return_rma_tenant",
        "logistics_tasks",
        "return_rmas",
        ["return_rma_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
