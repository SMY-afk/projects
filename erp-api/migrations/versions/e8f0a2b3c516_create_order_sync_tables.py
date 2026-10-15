"""create order sync and webhook tables

Revision ID: e8f0a2b3c516
Revises: d7e9f1a2b405
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f0a2b3c516"
down_revision: str | Sequence[str] | None = "d7e9f1a2b405"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_shop_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["shop_id", "tenant_id"], ["shops.id", "shops.tenant_id"], ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "order_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("window_from", sa.DateTime(timezone=True)),
        sa.Column("window_to", sa.DateTime(timezone=True)),
        sa.Column("recovery_cursor", sa.Text()),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("upserted_count", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_summary", sa.Text()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        _tenant_shop_fk(),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("shop_id", "status", "tenant_id"):
        op.create_index(
            op.f(f"ix_order_sync_runs_{column}"), "order_sync_runs", [column]
        )

    op.create_table(
        "order_sync_cursors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_cursor", sa.Text()),
        sa.Column("committed_cursor", sa.Text()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        _tenant_shop_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", name="uq_order_sync_cursors_shop"),
    )
    op.create_index(
        op.f("ix_order_sync_cursors_shop_id"), "order_sync_cursors", ["shop_id"]
    )
    op.create_index(
        op.f("ix_order_sync_cursors_tenant_id"), "order_sync_cursors", ["tenant_id"]
    )

    op.create_table(
        "tiktok_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform_event_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("object_id", sa.String(128)),
        sa.Column("payload_ciphertext", sa.Text()),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_summary", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        _tenant_shop_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_event_id", name="uq_tiktok_webhook_platform_event"
        ),
    )
    for column in ("shop_id", "status", "next_retry_at", "tenant_id"):
        op.create_index(
            op.f(f"ix_tiktok_webhook_events_{column}"),
            "tiktok_webhook_events",
            [column],
        )

    op.create_table(
        "pii_access_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("order_id", "actor_user_id", "tenant_id"):
        op.create_index(
            op.f(f"ix_pii_access_audits_{column}"), "pii_access_audits", [column]
        )


def downgrade() -> None:
    op.drop_table("pii_access_audits")
    op.drop_table("tiktok_webhook_events")
    op.drop_table("order_sync_cursors")
    op.drop_table("order_sync_runs")
