"""create exact order conversion links

Revision ID: b2c4d6e8f102
Revises: a7b8c9d0e1f2
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c4d6e8f102"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_conversion_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("source_system", sa.String(48), nullable=False),
        sa.Column("external_conversion_id", sa.String(160), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "order_id",
            "source_system",
            "external_conversion_id",
            "evidence_hash",
            name="uq_order_conversion_links_order_source_conversion_evidence",
        ),
    )
    op.create_index(
        "ix_order_conversion_links_order_id", "order_conversion_links", ["order_id"]
    )
    op.create_index(
        "ix_order_conversion_links_tenant_id", "order_conversion_links", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_conversion_links_tenant_id", table_name="order_conversion_links"
    )
    op.drop_index(
        "ix_order_conversion_links_order_id", table_name="order_conversion_links"
    )
    op.drop_table("order_conversion_links")
