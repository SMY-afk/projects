"""add sample notification outbox

Revision ID: 9bf2a3b4c5d6
Revises: 8ae1f2a3b4c5
Create Date: 2026-09-09 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9bf2a3b4c5d6"
down_revision: str | None = "8ae1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sample_notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sample_application_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("recipient_open_id", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_summary", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'retry_wait', "
            "'failed', 'cancelled')",
            name="ck_sample_notification_outbox_status",
        ),
        sa.CheckConstraint(
            "assignment_version > 0",
            name="ck_sample_notification_outbox_assignment_version",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_sample_notification_outbox_attempt_count",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sample_application_id", "tenant_id"],
            ["sample_applications.id", "sample_applications.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_sample_notification_outbox_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "sample_application_id",
            "assignment_version",
            "recipient_open_id",
            name="uq_sample_notification_outbox_assignment_recipient",
        ),
    )
    op.create_index(
        "ix_sample_notification_outbox_tenant_id",
        "sample_notification_outbox",
        ["tenant_id"],
    )
    op.create_index(
        "ix_sample_notification_outbox_due",
        "sample_notification_outbox",
        ["tenant_id", "status", "next_attempt_at"],
    )

    op.drop_constraint(
        "uq_sample_application_events_source_external",
        "sample_application_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sample_application_events_tenant_shop_source_external",
        "sample_application_events",
        ["tenant_id", "shop_id", "event_source", "external_event_id"],
    )
    op.alter_column(
        "sample_application_events",
        "before_data",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="before_data::jsonb",
    )
    op.alter_column(
        "sample_application_events",
        "after_data",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="after_data::jsonb",
    )
    op.execute(
        """
        CREATE FUNCTION prevent_sample_application_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'sample_application_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sample_application_events_append_only
        BEFORE UPDATE OR DELETE ON sample_application_events
        FOR EACH ROW EXECUTE FUNCTION prevent_sample_application_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sample_application_events_append_only "
        "ON sample_application_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_sample_application_event_mutation()")
    op.alter_column(
        "sample_application_events",
        "after_data",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        postgresql_using="after_data::json",
    )
    op.alter_column(
        "sample_application_events",
        "before_data",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        postgresql_using="before_data::json",
    )
    op.drop_constraint(
        "uq_sample_application_events_tenant_shop_source_external",
        "sample_application_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sample_application_events_source_external",
        "sample_application_events",
        ["event_source", "external_event_id"],
    )
    op.drop_index(
        "ix_sample_notification_outbox_due",
        table_name="sample_notification_outbox",
    )
    op.drop_index(
        "ix_sample_notification_outbox_tenant_id",
        table_name="sample_notification_outbox",
    )
    op.drop_table("sample_notification_outbox")
