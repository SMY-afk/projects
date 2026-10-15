"""add sample event actor id

Revision ID: 68c9d0e1f2a3
Revises: 57b8c9d0e1f2
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "68c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "57b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_application_events", sa.Column("actor_id", sa.String(255))
    )


def downgrade() -> None:
    op.drop_column("sample_application_events", "actor_id")
