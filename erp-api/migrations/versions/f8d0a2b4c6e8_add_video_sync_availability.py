"""add video sync availability metadata

Revision ID: f8d0a2b4c6e8
Revises: f7c9e1a3b5d4
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8d0a2b4c6e8"
down_revision: str | Sequence[str] | None = "f7c9e1a3b5d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analytics_sync_runs",
        sa.Column("currency", sa.String(3)),
    )
    op.add_column(
        "analytics_sync_runs",
        sa.Column("account_type", sa.String(32)),
    )
    op.add_column(
        "analytics_sync_runs",
        sa.Column("latest_available_date", sa.Date()),
    )
    op.execute(
        """
        UPDATE analytics_sync_runs AS run
        SET currency = snapshot.currency,
            account_type = snapshot.account_type
        FROM (
            SELECT sync_run_id,
                   MIN(currency) AS currency,
                   MIN(account_type) AS account_type
            FROM tiktok_video_performance_snapshots
            GROUP BY sync_run_id
        ) AS snapshot
        WHERE run.id = snapshot.sync_run_id
        """
    )
    op.create_index(
        "ix_analytics_sync_runs_video_window",
        "analytics_sync_runs",
        [
            "tenant_id",
            "shop_id",
            "resource_type",
            "window_start",
            "window_end",
            "currency",
            "account_type",
            "status",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_sync_runs_video_window",
        table_name="analytics_sync_runs",
    )
    op.drop_column("analytics_sync_runs", "latest_available_date")
    op.drop_column("analytics_sync_runs", "account_type")
    op.drop_column("analytics_sync_runs", "currency")
