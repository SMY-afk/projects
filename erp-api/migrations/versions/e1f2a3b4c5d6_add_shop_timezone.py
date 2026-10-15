"""add shop timezone

Revision ID: e1f2a3b4c5d6
Revises: d0e3f4a5b6c7
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("shops", "timezone")
