"""Separate free and refundable applications and capture watermarks."""

import sqlalchemy as sa
from alembic import op

revision = "b82c9d0e1f2a"
down_revision = "a71b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("sample_applications", "sample_ingest_batches", "sample_sync_runs"):
        op.add_column(table, sa.Column(
            "sample_type", sa.String(16), nullable=False, server_default="free"
        ))
        op.create_check_constraint(
            f"ck_{table}_sample_type", table, "sample_type IN ('free', 'refundable')"
        )
    op.create_index(
        "ix_sample_batches_shop_type_finished", "sample_ingest_batches",
        ["tenant_id", "shop_id", "sample_type", "finished_at"],
    )


def downgrade():
    op.drop_index("ix_sample_batches_shop_type_finished", table_name="sample_ingest_batches")
    for table in ("sample_sync_runs", "sample_ingest_batches", "sample_applications"):
        op.drop_constraint(f"ck_{table}_sample_type", table, type_="check")
        op.drop_column(table, "sample_type")
