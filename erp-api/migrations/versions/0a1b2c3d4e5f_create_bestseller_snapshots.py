"""create bestseller snapshot and entry tables

Revision ID: 0a1b2c3d4e5f
Revises: f8d0a2b4c6e8
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "f8d0a2b4c6e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bestseller_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("time_slot", sa.String(4), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("author_type", sa.String(16), nullable=False),
        sa.Column("platform_request_id", sa.String(128), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_bestseller_snapshots_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "entity_type",
            "reference_date",
            "time_slot",
            "currency",
            "author_type",
            name="uq_bestseller_snapshots_query",
        ),
    )
    op.create_index(
        "ix_bestseller_snapshots_shop_id", "bestseller_snapshots", ["shop_id"]
    )
    op.create_index(
        "ix_bestseller_snapshots_tenant_id",
        "bestseller_snapshots",
        ["tenant_id"],
    )
    op.create_index(
        "ix_bestseller_snapshots_shop_entity_date",
        "bestseller_snapshots",
        ["tenant_id", "shop_id", "entity_type", "reference_date"],
    )
    op.create_table(
        "bestseller_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("gmv_range_raw", sa.Text(), nullable=False),
        sa.Column("gmv_currency_context", sa.String(8), nullable=False),
        sa.Column("extensions", postgresql.JSONB(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "tenant_id"],
            ["bestseller_snapshots.id", "bestseller_snapshots.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "external_id",
            name="uq_bestseller_entries_snapshot_external",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "rank", name="uq_bestseller_entries_snapshot_rank"
        ),
    )
    op.create_index(
        "ix_bestseller_entries_tenant_id", "bestseller_entries", ["tenant_id"]
    )
    op.create_index(
        "ix_bestseller_entries_tenant_snapshot_rank",
        "bestseller_entries",
        ["tenant_id", "snapshot_id", "rank"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bestseller_entries_tenant_snapshot_rank",
        table_name="bestseller_entries",
    )
    op.drop_index("ix_bestseller_entries_tenant_id", table_name="bestseller_entries")
    op.drop_table("bestseller_entries")
    op.drop_index(
        "ix_bestseller_snapshots_shop_entity_date",
        table_name="bestseller_snapshots",
    )
    op.drop_index(
        "ix_bestseller_snapshots_tenant_id", table_name="bestseller_snapshots"
    )
    op.drop_index("ix_bestseller_snapshots_shop_id", table_name="bestseller_snapshots")
    op.drop_table("bestseller_snapshots")
