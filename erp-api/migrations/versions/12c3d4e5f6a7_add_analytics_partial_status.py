"""add analytics partial status

Revision ID: 12c3d4e5f6a7
Revises: 01b2c3d4e5f6
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "12c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "01b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_CHECK = (
    "status IN ('queued', 'running', 'retry_wait', 'succeeded', "
    "'partial', 'failed', 'dead_letter', 'cancelled')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_analytics_sync_runs_status",
        "analytics_sync_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_analytics_sync_runs_status",
        "analytics_sync_runs",
        _STATUS_CHECK,
    )


def downgrade() -> None:
    connection = op.get_bind()
    partial_count = connection.scalar(
        sa.text("SELECT count(*) FROM analytics_sync_runs WHERE status = 'partial'")
    )
    if partial_count:
        raise RuntimeError("Cannot remove partial status while partial runs exist.")
    op.drop_constraint(
        "ck_analytics_sync_runs_status",
        "analytics_sync_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_analytics_sync_runs_status",
        "analytics_sync_runs",
        _STATUS_CHECK.replace("'partial', ", ""),
    )
