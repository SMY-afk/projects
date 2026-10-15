"""add platform fulfillment outbox

Revision ID: f36e7f8091a2
Revises: e25d6e7f8091
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f36e7f8091a2"
down_revision: str | Sequence[str] | None = "e25d6e7f8091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_fulfillment_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("waybill_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("platform_order_id", sa.String(128), nullable=False),
        sa.Column("platform_package_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_summary", sa.Text()),
        sa.Column("platform_request_id", sa.String(128)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("version_id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["package_id", "tenant_id"],
            ["logistics_packages.id", "logistics_packages.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "event_type = 'shipment_confirmed'",
            name="ck_platform_fulfillment_outbox_event_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry_wait', "
            "'succeeded', 'failed', 'skipped')",
            name="ck_platform_fulfillment_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_platform_fulfillment_outbox_attempts"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_platform_fulfillment_outbox_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_platform_fulfillment_outbox_tenant_key",
        ),
    )
    op.create_index(
        "ix_platform_fulfillment_outbox_tenant_id",
        "platform_fulfillment_outbox",
        ["tenant_id"],
    )
    op.create_index(
        "ix_platform_fulfillment_outbox_due",
        "platform_fulfillment_outbox",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("platform_fulfillment_outbox")
