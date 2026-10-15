"""Add TikTok return and refund synchronization fields.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "return_requests",
        sa.Column("source", sa.String(16), nullable=False, server_default="local"),
    )
    op.add_column("return_requests", sa.Column("platform", sa.String(32)))
    op.add_column("return_requests", sa.Column("platform_return_id", sa.String(128)))
    op.add_column("return_requests", sa.Column("platform_status", sa.String(128)))
    op.add_column("return_requests", sa.Column("platform_reason_text", sa.Text()))
    op.add_column(
        "return_requests", sa.Column("platform_created_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "return_requests", sa.Column("platform_updated_at", sa.DateTime(timezone=True))
    )
    op.add_column("return_requests", sa.Column("refund_currency", sa.String(3)))
    op.add_column("return_requests", sa.Column("refund_amount_minor", sa.BigInteger()))
    op.add_column("return_requests", sa.Column("raw_payload", postgresql.JSONB()))
    op.alter_column("return_requests", "created_by_user_id", nullable=True)
    op.drop_constraint("ck_return_requests_type", "return_requests", type_="check")
    op.create_check_constraint(
        "ck_return_requests_type",
        "return_requests",
        "request_type IN ('return', 'exchange', 'refund')",
    )
    op.create_check_constraint(
        "ck_return_requests_source",
        "return_requests",
        "source IN ('local', 'platform')",
    )
    op.create_check_constraint(
        "ck_return_requests_platform_source",
        "return_requests",
        "(source = 'local' AND platform IS NULL AND platform_return_id IS NULL) OR "
        "(source = 'platform' AND platform IS NOT NULL AND platform_return_id IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_return_requests_platform_identity",
        "return_requests",
        ["tenant_id", "shop_id", "platform", "platform_return_id"],
    )
    op.create_index(
        "ix_return_requests_platform_updated",
        "return_requests",
        ["tenant_id", "shop_id", "platform_updated_at"],
    )
    op.add_column(
        "return_request_items",
        sa.Column("platform_return_line_id", sa.String(128)),
    )
    op.create_unique_constraint(
        "uq_return_request_items_platform_line",
        "return_request_items",
        ["tenant_id", "platform_return_line_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_return_request_items_platform_line",
        "return_request_items",
        type_="unique",
    )
    op.drop_column("return_request_items", "platform_return_line_id")
    op.drop_index("ix_return_requests_platform_updated", table_name="return_requests")
    op.drop_constraint(
        "uq_return_requests_platform_identity", "return_requests", type_="unique"
    )
    op.execute(sa.text("DELETE FROM return_requests WHERE source = 'platform'"))
    op.drop_constraint(
        "ck_return_requests_platform_source", "return_requests", type_="check"
    )
    op.drop_constraint("ck_return_requests_source", "return_requests", type_="check")
    op.drop_constraint("ck_return_requests_type", "return_requests", type_="check")
    op.create_check_constraint(
        "ck_return_requests_type",
        "return_requests",
        "request_type IN ('return', 'exchange')",
    )
    op.alter_column("return_requests", "created_by_user_id", nullable=False)
    for column in (
        "raw_payload",
        "refund_amount_minor",
        "refund_currency",
        "platform_updated_at",
        "platform_created_at",
        "platform_reason_text",
        "platform_status",
        "platform_return_id",
        "platform",
        "source",
    ):
        op.drop_column("return_requests", column)
