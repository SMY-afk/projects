"""add logistics exception center

Revision ID: b58f7a9012c4
Revises: a47e6f8091b3
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b58f7a9012c4"
down_revision: str | Sequence[str] | None = "a47e6f8091b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "logistics_exceptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exception_number", sa.String(40), nullable=False),
        sa.Column("waybill_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid()),
        sa.Column("exception_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("fingerprint", sa.String(160), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("assigned_to_user_id", sa.Uuid()),
        sa.Column("resolution", sa.Text()),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
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
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["package_id", "tenant_id"],
            ["logistics_packages.id", "logistics_packages.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_logistics_exceptions_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "exception_number",
            name="uq_logistics_exceptions_tenant_number",
        ),
        sa.CheckConstraint(
            "exception_type IN ('not_picked_up', 'stalled', 'address_error', 'refused', 'lost', 'damaged', 'platform_status_mismatch')",
            name="ck_logistics_exceptions_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'claimed', 'escalated', 'resolved', 'closed')",
            name="ck_logistics_exceptions_status",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_logistics_exceptions_severity",
        ),
        sa.CheckConstraint(
            "source IN ('tracking_event', 'scheduled_scan')",
            name="ck_logistics_exceptions_source",
        ),
    )
    op.create_index(
        "ix_logistics_exceptions_tenant_id", "logistics_exceptions", ["tenant_id"]
    )
    op.create_index(
        "ix_logistics_exceptions_center",
        "logistics_exceptions",
        ["tenant_id", "status", "severity", "last_detected_at"],
    )
    op.create_index(
        "uq_logistics_exceptions_active_fingerprint",
        "logistics_exceptions",
        ["tenant_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("status != 'closed'"),
    )
    _create_actions()


def _create_actions() -> None:
    op.create_table(
        "logistics_exception_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exception_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(24), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20)),
        sa.Column("note", sa.Text()),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["exception_id", "tenant_id"],
            ["logistics_exceptions.id", "logistics_exceptions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "action_type IN ('detected', 'claimed', 'note_added', 'escalated', 'resolved', 'closed')",
            name="ck_logistics_exception_actions_type",
        ),
    )
    op.create_index(
        "ix_logistics_exception_actions_tenant_id",
        "logistics_exception_actions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_logistics_exception_actions_timeline",
        "logistics_exception_actions",
        ["tenant_id", "exception_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("logistics_exception_actions")
    op.drop_table("logistics_exceptions")
