"""change scraped raw data to json

Revision ID: c5e6f7a8b9d0
Revises: b4d5e6f7a8c9
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5e6f7a8b9d0"
down_revision: str | Sequence[str] | None = "b4d5e6f7a8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "scraped_data",
        "raw_data",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        existing_nullable=False,
        postgresql_using="raw_data::json",
    )


def downgrade() -> None:
    op.alter_column(
        "scraped_data",
        "raw_data",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        postgresql_using="raw_data::jsonb",
    )
