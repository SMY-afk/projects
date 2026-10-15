"""Persist sample Feishu incremental sync state.

Revision ID: a71b8c9d0e1f
Revises: f159a2b3c4d5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a71b8c9d0e1f"
down_revision: str | None = "f159a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_application_workflows",
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sample_application_workflows",
        sa.Column("sync_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sample_application_workflows",
        sa.Column(
            "sync_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_sample_application_workflows_sync_status",
        "sample_application_workflows",
        "sync_status IN ('pending', 'succeeded', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sample_application_workflows_sync_status",
        "sample_application_workflows",
        type_="check",
    )
    op.drop_column("sample_application_workflows", "sync_status")
    op.drop_column("sample_application_workflows", "sync_hash")
    op.drop_column("sample_application_workflows", "last_sync_at")
