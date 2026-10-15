"""Reconcile tenant indexes and foreign keys.

Revision ID: 46a7b8c9d0e1
Revises: 35f6a7b8c9d0
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "46a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "35f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in (
        "affiliate_creator_detail_reports",
        "affiliate_creator_detail_items",
        "return_requests",
        "return_request_items",
        "return_rmas",
    ):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    op.create_foreign_key(
        "fk_affiliate_creator_detail_reports_tenant",
        "affiliate_creator_detail_reports",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_affiliate_creator_detail_items_tenant",
        "affiliate_creator_detail_items",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_affiliate_creator_detail_items_tenant",
        "affiliate_creator_detail_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_affiliate_creator_detail_reports_tenant",
        "affiliate_creator_detail_reports",
        type_="foreignkey",
    )

    for table in reversed(
        (
            "affiliate_creator_detail_reports",
            "affiliate_creator_detail_items",
            "return_requests",
            "return_request_items",
            "return_rmas",
        )
    ):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
