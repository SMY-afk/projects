"""make scraped platform id globally unique

Revision ID: d6f7a8b9c0e1
Revises: c5e6f7a8b9d0
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d6f7a8b9c0e1"
down_revision: str | Sequence[str] | None = "c5e6f7a8b9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_scraped_data_tenant_platform_id",
        "scraped_data",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_scraped_data_platform_id",
        "scraped_data",
        ["platform_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_scraped_data_platform_id",
        "scraped_data",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_scraped_data_tenant_platform_id",
        "scraped_data",
        ["tenant_id", "platform_id"],
    )
