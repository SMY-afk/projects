"""store encrypted TikTok shop cipher"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f8c1e2d7b6"
down_revision: str | Sequence[str] | None = "9d3e7f2a5c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shop_connections", sa.Column("shop_ciphertext", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("shop_connections", "shop_ciphertext")
