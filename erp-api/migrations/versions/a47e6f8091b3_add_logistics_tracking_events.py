"""add logistics tracking events

Revision ID: a47e6f8091b3
Revises: f36e7f8091a2
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a47e6f8091b3"
down_revision: str | Sequence[str] | None = "f36e7f8091a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "logistics_waybills", sa.Column("tracking_number_hash", sa.String(64))
    )
    op.add_column("logistics_waybills", sa.Column("tracking_status", sa.String(32)))
    op.add_column(
        "logistics_waybills",
        sa.Column("tracking_occurred_at", sa.DateTime(timezone=True)),
    )
    op.add_column("logistics_waybills", sa.Column("tracking_sequence", sa.BigInteger()))
    op.add_column(
        "logistics_waybills",
        sa.Column("tracking_last_polled_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "logistics_waybills",
        sa.Column("tracking_next_poll_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "logistics_waybills",
        sa.Column(
            "tracking_poll_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "logistics_waybills", sa.Column("tracking_poll_error_code", sa.String(64))
    )
    op.create_check_constraint(
        "ck_logistics_waybills_tracking_status",
        "logistics_waybills",
        "tracking_status IS NULL OR tracking_status IN "
        "('info_received', 'picked_up', 'in_transit', 'out_for_delivery', "
        "'delivered', 'exception', 'returned', 'cancelled')",
    )
    op.create_index(
        "ix_logistics_waybills_tracking_number_hash",
        "logistics_waybills",
        ["tracking_number_hash"],
    )
    op.create_index(
        "ix_logistics_waybills_tracking_next_poll_at",
        "logistics_waybills",
        ["tracking_next_poll_at"],
    )
    op.create_table(
        "logistics_tracking_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("waybill_id", sa.Uuid(), nullable=False),
        sa.Column("carrier_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_event_id", sa.String(160)),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("raw_status", sa.String(128), nullable=False),
        sa.Column("normalized_status", sa.String(32)),
        sa.Column("sequence_no", sa.BigInteger()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("location", sa.String(500)),
        sa.Column("description", sa.Text()),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("ignored_reason", sa.String(64)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "waybill_id",
            "dedupe_key",
            name="uq_logistics_tracking_events_dedupe",
        ),
        sa.CheckConstraint(
            "source IN ('webhook', 'poll')", name="ck_logistics_tracking_events_source"
        ),
        sa.CheckConstraint(
            "normalized_status IS NULL OR normalized_status IN "
            "('info_received', 'picked_up', 'in_transit', 'out_for_delivery', "
            "'delivered', 'exception', 'returned', 'cancelled')",
            name="ck_logistics_tracking_events_status",
        ),
    )
    op.create_index(
        "ix_logistics_tracking_events_tenant_id",
        "logistics_tracking_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_logistics_tracking_events_timeline",
        "logistics_tracking_events",
        ["tenant_id", "waybill_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("logistics_tracking_events")
    op.drop_constraint(
        "ck_logistics_waybills_tracking_status", "logistics_waybills", type_="check"
    )
    op.drop_index(
        "ix_logistics_waybills_tracking_next_poll_at", table_name="logistics_waybills"
    )
    op.drop_index(
        "ix_logistics_waybills_tracking_number_hash", table_name="logistics_waybills"
    )
    for column in (
        "tracking_poll_error_code",
        "tracking_poll_attempt_count",
        "tracking_next_poll_at",
        "tracking_last_polled_at",
        "tracking_sequence",
        "tracking_occurred_at",
        "tracking_status",
        "tracking_number_hash",
    ):
        op.drop_column("logistics_waybills", column)
