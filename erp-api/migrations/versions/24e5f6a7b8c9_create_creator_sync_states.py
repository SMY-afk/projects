"""create creator sync states

Revision ID: 24e5f6a7b8c9
Revises: 13d4e5f6a7b8
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "24e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "13d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_sync_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.String(length=128), nullable=False),
        sa.Column("affiliate_creator_id", sa.Uuid(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_video_sync_at", sa.DateTime(timezone=True)),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "sync_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "sync_status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_creator_sync_states_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            name="fk_creator_sync_states_shop_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["affiliate_creator_id", "tenant_id", "shop_id"],
            [
                "affiliate_creators.id",
                "affiliate_creators.tenant_id",
                "affiliate_creators.shop_id",
            ],
            name="fk_creator_sync_states_creator_tenant_shop",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "creator_id",
            name="uq_creator_sync_states_creator",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "affiliate_creator_id",
            name="uq_creator_sync_states_affiliate_creator",
        ),
    )
    op.create_index(
        "ix_creator_sync_states_due",
        "creator_sync_states",
        ["tenant_id", "shop_id", "sync_status", "last_sync_at"],
    )
    op.create_index(
        "ix_creator_sync_states_tenant_id",
        "creator_sync_states",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_sync_states_tenant_id", table_name="creator_sync_states")
    op.drop_index("ix_creator_sync_states_due", table_name="creator_sync_states")
    op.drop_table("creator_sync_states")
