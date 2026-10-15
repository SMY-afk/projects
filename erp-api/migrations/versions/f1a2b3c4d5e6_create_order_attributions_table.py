"""create order attributions table

Revision ID: f1a2b3c4d5e6
Revises: e8f0a2b3c516
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e8f0a2b3c516"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_attributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("traffic_source", sa.String(32), nullable=False),
        sa.Column("operator_subject", sa.String(32), nullable=False),
        sa.Column("entry_point", sa.String(48), nullable=False),
        sa.Column("special_order_type", sa.String(48), nullable=False),
        sa.Column("chain_code", sa.String(160), nullable=False),
        sa.Column("classification_status", sa.String(24), nullable=False),
        sa.Column("classification_method", sa.String(32), nullable=False),
        sa.Column("platform_source_code", sa.String(128)),
        sa.Column("creator_external_id", sa.String(128)),
        sa.Column("campaign_external_id", sa.String(128)),
        sa.Column("evidence_json", postgresql.JSONB()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column(
            "classified_at",
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
            name="uq_order_attributions_tenant_order",
        ),
    )
    op.create_index(
        "ix_order_attributions_order_id",
        "order_attributions",
        ["order_id"],
    )
    op.create_index(
        "ix_order_attributions_tenant_chain_code",
        "order_attributions",
        ["tenant_id", "chain_code"],
    )
    op.create_index(
        "ix_order_attributions_tenant_classification_status",
        "order_attributions",
        ["tenant_id", "classification_status"],
    )
    op.create_index(
        "ix_order_attributions_tenant_id",
        "order_attributions",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_attributions_tenant_id", table_name="order_attributions")
    op.drop_index(
        "ix_order_attributions_tenant_classification_status",
        table_name="order_attributions",
    )
    op.drop_index(
        "ix_order_attributions_tenant_chain_code", table_name="order_attributions"
    )
    op.drop_index("ix_order_attributions_order_id", table_name="order_attributions")
    op.drop_table("order_attributions")
