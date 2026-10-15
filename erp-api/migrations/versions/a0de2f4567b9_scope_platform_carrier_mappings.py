"""Scope platform carrier mappings to stores and delivery options.

Revision ID: a0de2f4567b9
Revises: f9cd1e3456a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a0de2f4567b9"
down_revision: str | Sequence[str] | None = "f9cd1e3456a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "logistics_platform_carrier_mappings"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("store_id", sa.Uuid(), nullable=True))
    op.add_column(
        TABLE, sa.Column("platform_carrier_id", sa.String(128), nullable=True)
    )
    op.add_column(TABLE, sa.Column("delivery_option_id", sa.String(128)))
    op.add_column(
        TABLE,
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("order_fulfillments", sa.Column("delivery_option_id", sa.String(128)))
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE} AS mapping
            SET platform_carrier_id = mapping.platform_carrier_code,
                store_id = (
                    SELECT shop.id
                    FROM shops AS shop
                    WHERE shop.tenant_id = mapping.tenant_id
                      AND lower(shop.platform) = lower(mapping.platform)
                    ORDER BY
                      CASE
                        WHEN upper(coalesce(shop.region, '')) = mapping.region THEN 0
                        ELSE 1
                      END,
                      shop.created_at,
                      shop.id
                    LIMIT 1
                )
            """
        )
    )
    op.alter_column(TABLE, "store_id", nullable=False)
    op.alter_column(TABLE, "platform_carrier_id", nullable=False)
    op.alter_column(TABLE, "platform_carrier_code", nullable=True)
    op.create_foreign_key(
        "fk_logistics_platform_carrier_mappings_store_tenant",
        TABLE,
        "shops",
        ["store_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    _drop_old_indexes()
    _create_indexes()


def downgrade() -> None:
    _drop_indexes()
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
            SET platform_carrier_code = coalesce(
                platform_carrier_code, platform_carrier_id
            )
            """
        )
    )
    op.alter_column(TABLE, "platform_carrier_code", nullable=False)
    op.drop_constraint(
        "fk_logistics_platform_carrier_mappings_store_tenant",
        TABLE,
        type_="foreignkey",
    )
    op.drop_column("order_fulfillments", "delivery_option_id")
    op.drop_column(TABLE, "raw_payload")
    op.drop_column(TABLE, "delivery_option_id")
    op.drop_column(TABLE, "platform_carrier_id")
    op.drop_column(TABLE, "store_id")
    _create_old_indexes()


def _drop_old_indexes() -> None:
    for name in (
        "ix_logistics_platform_carrier_mappings_lookup",
        "uq_logistics_platform_carrier_mappings_service_scope",
        "uq_logistics_platform_carrier_mappings_carrier_scope",
        "uq_logistics_platform_carrier_mappings_external",
    ):
        op.drop_index(name, table_name=TABLE)


def _create_indexes() -> None:
    specs = (
        (
            "external_default",
            ["tenant_id", "store_id", "platform", "platform_carrier_id"],
            "delivery_option_id IS NULL",
        ),
        (
            "external_option",
            [
                "tenant_id",
                "store_id",
                "platform",
                "delivery_option_id",
                "platform_carrier_id",
            ],
            "delivery_option_id IS NOT NULL",
        ),
        (
            "carrier_default",
            ["tenant_id", "store_id", "platform", "carrier_id"],
            "service_id IS NULL AND delivery_option_id IS NULL",
        ),
        (
            "carrier_option",
            ["tenant_id", "store_id", "platform", "delivery_option_id", "carrier_id"],
            "service_id IS NULL AND delivery_option_id IS NOT NULL",
        ),
        (
            "service_default",
            ["tenant_id", "store_id", "platform", "service_id"],
            "service_id IS NOT NULL AND delivery_option_id IS NULL",
        ),
        (
            "service_option",
            ["tenant_id", "store_id", "platform", "delivery_option_id", "service_id"],
            "service_id IS NOT NULL AND delivery_option_id IS NOT NULL",
        ),
    )
    for suffix, columns, predicate in specs:
        op.create_index(
            f"uq_logistics_platform_carrier_mappings_{suffix}",
            TABLE,
            columns,
            unique=True,
            postgresql_where=sa.text(predicate),
        )
    op.create_index(
        "ix_logistics_platform_carrier_mappings_lookup",
        TABLE,
        [
            "tenant_id",
            "store_id",
            "platform",
            "delivery_option_id",
            "carrier_id",
            "service_id",
            "status",
        ],
    )


def _drop_indexes() -> None:
    op.drop_index("ix_logistics_platform_carrier_mappings_lookup", table_name=TABLE)
    for suffix in (
        "service_option",
        "service_default",
        "carrier_option",
        "carrier_default",
        "external_option",
        "external_default",
    ):
        op.drop_index(
            f"uq_logistics_platform_carrier_mappings_{suffix}", table_name=TABLE
        )


def _create_old_indexes() -> None:
    op.create_index(
        "uq_logistics_platform_carrier_mappings_external",
        TABLE,
        ["tenant_id", "platform", "region", "platform_carrier_code"],
        unique=True,
    )
    op.create_index(
        "uq_logistics_platform_carrier_mappings_carrier_scope",
        TABLE,
        ["tenant_id", "platform", "region", "carrier_id"],
        unique=True,
        postgresql_where=sa.text("service_id IS NULL"),
    )
    op.create_index(
        "uq_logistics_platform_carrier_mappings_service_scope",
        TABLE,
        ["tenant_id", "platform", "region", "service_id"],
        unique=True,
        postgresql_where=sa.text("service_id IS NOT NULL"),
    )
    op.create_index(
        "ix_logistics_platform_carrier_mappings_lookup",
        TABLE,
        ["tenant_id", "platform", "region", "carrier_id", "service_id", "status"],
    )
