"""create affiliate sync states table

Revision ID: a3c4d5e6f7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c4d5e6f7b8"
down_revision: str | Sequence[str] | None = "f2b3c4d5e6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "affiliate_sync_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("next_cursor", sa.Text()),
        sa.Column(
            "has_more",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            name="uq_affiliate_sync_states_shop",
        ),
    )
    op.create_index(
        "ix_affiliate_sync_states_shop_id",
        "affiliate_sync_states",
        ["shop_id"],
    )
    op.create_index(
        "ix_affiliate_sync_states_tenant_id",
        "affiliate_sync_states",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_sync_states_tenant_id",
        table_name="affiliate_sync_states",
    )
    op.drop_index(
        "ix_affiliate_sync_states_shop_id",
        table_name="affiliate_sync_states",
    )
    op.drop_table("affiliate_sync_states")
