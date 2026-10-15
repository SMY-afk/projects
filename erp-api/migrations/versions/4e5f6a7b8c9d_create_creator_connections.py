"""create creator connections

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4e5f6a7b8c9d"
down_revision: str | Sequence[str] | None = "3d4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("open_id", sa.String(length=255), nullable=False),
        sa.Column("user_type", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=30), nullable=True),
        sa.Column("auth_status", sa.String(length=32), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("user_type = 1", name="ck_creator_connections_user_type"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "platform",
            "open_id",
            name="uq_creator_connections_tenant_platform_open_id",
        ),
    )
    op.create_index(
        "ix_creator_connections_tenant_id",
        "creator_connections",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_connections_tenant_id", table_name="creator_connections")
    op.drop_table("creator_connections")
