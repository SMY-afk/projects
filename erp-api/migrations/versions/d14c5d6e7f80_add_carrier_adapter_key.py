"""add carrier adapter key

Revision ID: d14c5d6e7f80
Revises: c03b4c5d6e7f
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d14c5d6e7f80"
down_revision: str | Sequence[str] | None = "c03b4c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "logistics_carriers",
        sa.Column(
            "adapter_key",
            sa.String(64),
            server_default="manual",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("logistics_carriers", "adapter_key")
