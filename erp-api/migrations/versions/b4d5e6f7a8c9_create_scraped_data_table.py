"""create scraped data table

Revision ID: b4d5e6f7a8c9
Revises: a3c4d5e6f7b8
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4d5e6f7a8c9"
down_revision: str | Sequence[str] | None = "a3c4d5e6f7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scraped_data",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.String(100), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("creator_id", sa.String(100)),
        sa.Column("creator_name", sa.String(255)),
        sa.Column("title", sa.Text()),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "platform_id",
            name="uq_scraped_data_tenant_platform_id",
        ),
    )
    op.create_index(
        "ix_scraped_data_creator_id",
        "scraped_data",
        ["creator_id"],
    )
    op.create_index(
        "ix_scraped_data_data_type",
        "scraped_data",
        ["data_type"],
    )
    op.create_index(
        "ix_scraped_data_tenant_id",
        "scraped_data",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scraped_data_tenant_id", table_name="scraped_data")
    op.drop_index("ix_scraped_data_data_type", table_name="scraped_data")
    op.drop_index("ix_scraped_data_creator_id", table_name="scraped_data")
    op.drop_table("scraped_data")
