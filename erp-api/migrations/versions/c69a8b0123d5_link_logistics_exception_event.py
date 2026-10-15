"""link logistics exceptions to tenant tracking events

Revision ID: c69a8b0123d5
Revises: b58f7a9012c4
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c69a8b0123d5"
down_revision: str | Sequence[str] | None = "b58f7a9012c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_logistics_tracking_events_id_tenant",
        "logistics_tracking_events",
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_logistics_exceptions_source_event_tenant",
        "logistics_exceptions",
        "logistics_tracking_events",
        ["source_event_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_logistics_exceptions_source_event_tenant",
        "logistics_exceptions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_logistics_tracking_events_id_tenant",
        "logistics_tracking_events",
        type_="unique",
    )
