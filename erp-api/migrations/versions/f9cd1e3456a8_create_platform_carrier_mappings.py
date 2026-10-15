"""create platform carrier mappings

Revision ID: f9cd1e3456a8
Revises: e8bc0d2345f7
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9cd1e3456a8"
down_revision: str | Sequence[str] | None = "e8bc0d2345f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "logistics_platform_carrier_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("carrier_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column(
            "region", sa.String(length=32), server_default="GLOBAL", nullable=False
        ),
        sa.Column("platform_carrier_code", sa.String(length=128), nullable=False),
        sa.Column("platform_carrier_name", sa.String(length=128), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="active", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version_id", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_logistics_platform_carrier_mappings_status",
        ),
        sa.ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id", "carrier_id", "tenant_id"],
            [
                "logistics_carrier_services.id",
                "logistics_carrier_services.carrier_id",
                "logistics_carrier_services.tenant_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_logistics_platform_carrier_mappings_id_tenant",
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    )
    _create_indexes()
    _backfill_legacy_provider_ids()


def _create_indexes() -> None:
    table = "logistics_platform_carrier_mappings"
    op.create_index(
        "ix_logistics_platform_carrier_mappings_tenant_id",
        table,
        ["tenant_id"],
    )
    op.create_index(
        "uq_logistics_platform_carrier_mappings_external",
        table,
        ["tenant_id", "platform", "region", "platform_carrier_code"],
        unique=True,
    )
    op.create_index(
        "uq_logistics_platform_carrier_mappings_carrier_scope",
        table,
        ["tenant_id", "platform", "region", "carrier_id"],
        unique=True,
        postgresql_where=sa.text("service_id IS NULL"),
    )
    op.create_index(
        "uq_logistics_platform_carrier_mappings_service_scope",
        table,
        ["tenant_id", "platform", "region", "service_id"],
        unique=True,
        postgresql_where=sa.text("service_id IS NOT NULL"),
    )
    op.create_index(
        "ix_logistics_platform_carrier_mappings_lookup",
        table,
        ["tenant_id", "platform", "region", "carrier_id", "service_id", "status"],
    )


def _backfill_legacy_provider_ids() -> None:
    op.execute(
        """
        WITH legacy AS (
            SELECT
                service.tenant_id,
                service.carrier_id,
                service.id AS service_id,
                lower(left(entry.key, -length('ShippingProviderId'))) AS platform,
                entry.value AS provider_id
            FROM logistics_carrier_services AS service
            CROSS JOIN LATERAL jsonb_each_text(service.configuration) AS entry
            WHERE entry.key LIKE '%ShippingProviderId'
              AND btrim(entry.value) <> ''
        ), summarized AS (
            SELECT
                tenant_id,
                carrier_id,
                platform,
                provider_id,
                min(service_id::text)::uuid AS sample_service_id,
                (
                    SELECT count(DISTINCT peer.provider_id)
                    FROM legacy AS peer
                    WHERE peer.tenant_id = legacy.tenant_id
                      AND peer.carrier_id = legacy.carrier_id
                      AND peer.platform = legacy.platform
                ) AS provider_count
            FROM legacy
            GROUP BY tenant_id, carrier_id, platform, provider_id
        )
        INSERT INTO logistics_platform_carrier_mappings (
            id, tenant_id, carrier_id, service_id, platform, region,
            platform_carrier_code, status, version_id
        )
        SELECT
            md5(tenant_id::text || ':' || carrier_id::text || ':' || platform || ':' || provider_id)::uuid,
            tenant_id,
            carrier_id,
            CASE WHEN provider_count = 1 THEN NULL ELSE sample_service_id END,
            platform,
            'GLOBAL',
            provider_id,
            'active',
            1
        FROM summarized
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("logistics_platform_carrier_mappings")
