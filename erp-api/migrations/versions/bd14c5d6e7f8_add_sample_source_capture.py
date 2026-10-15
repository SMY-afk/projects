"""add sample source capture

Revision ID: bd14c5d6e7f8
Revises: ac03b4c5d6e7
Create Date: 2026-09-10 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bd14c5d6e7f8"
down_revision: str | None = "ac03b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_sample_ingest_batches_id_tenant_shop",
        "sample_ingest_batches",
        ["id", "tenant_id", "shop_id"],
    )
    op.add_column(
        "sample_applications",
        sa.Column("source_capture_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sample_applications_source_capture_scope",
        "sample_applications",
        "sample_ingest_batches",
        ["source_capture_id", "tenant_id", "shop_id"],
        ["id", "tenant_id", "shop_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_sample_applications_source_capture",
        "sample_applications",
        ["tenant_id", "shop_id", "source_capture_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sample_applications_source_capture",
        table_name="sample_applications",
    )
    op.drop_constraint(
        "fk_sample_applications_source_capture_scope",
        "sample_applications",
        type_="foreignkey",
    )
    op.drop_column("sample_applications", "source_capture_id")
    op.drop_constraint(
        "uq_sample_ingest_batches_id_tenant_shop",
        "sample_ingest_batches",
        type_="unique",
    )
