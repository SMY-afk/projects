"""index product SKU tenant scope

Revision ID: e8bc0d2345f7
Revises: d7ab9c1234e6
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8bc0d2345f7"
down_revision: str | Sequence[str] | None = "d7ab9c1234e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_product_skus_tenant_id", "product_skus", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_product_skus_tenant_id", table_name="product_skus")
