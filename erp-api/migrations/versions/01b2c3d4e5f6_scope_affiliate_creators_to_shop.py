"""scope affiliate creator reporting to tenant and shop

Revision ID: 01b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "01b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("affiliate_creators", sa.Column("shop_id", sa.Uuid()))
    op.add_column("affiliate_creator_metrics", sa.Column("shop_id", sa.Uuid()))
    op.execute(
        """
        UPDATE affiliate_creator_metrics AS metric
        SET shop_id = report.shop_id
        FROM affiliate_creator_reports AS report
        WHERE report.id = metric.report_id
          AND report.tenant_id = metric.tenant_id
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE affiliate_creator_shop_map ON COMMIT DROP AS
        SELECT creator_id AS old_creator_id,
               tenant_id,
               shop_id,
               CASE
                   WHEN row_number() OVER (
                       PARTITION BY creator_id ORDER BY shop_id
                   ) = 1 THEN creator_id
                   ELSE gen_random_uuid()
               END AS new_creator_id
        FROM (
            SELECT DISTINCT creator_id, tenant_id, shop_id
            FROM affiliate_creator_metrics
        ) AS usage
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM affiliate_creators AS creator
                LEFT JOIN affiliate_creator_shop_map AS mapping
                  ON mapping.old_creator_id = creator.id
                 AND mapping.tenant_id = creator.tenant_id
                WHERE mapping.old_creator_id IS NULL
            ) THEN
                RAISE EXCEPTION 'Cannot infer shop for an orphan affiliate creator';
            END IF;
        END $$
        """
    )
    _drop_old_constraints()
    op.execute(
        """
        INSERT INTO affiliate_creators (
            id, shop_id, username, username_normalized, creator_open_id,
            avatar_url, source_identifiers, extensions, first_seen_at,
            last_seen_at, tenant_id
        )
        SELECT mapping.new_creator_id, mapping.shop_id, creator.username,
               creator.username_normalized, creator.creator_open_id,
               creator.avatar_url, creator.source_identifiers,
               creator.extensions, creator.first_seen_at,
               creator.last_seen_at, creator.tenant_id
        FROM affiliate_creator_shop_map AS mapping
        JOIN affiliate_creators AS creator
          ON creator.id = mapping.old_creator_id
         AND creator.tenant_id = mapping.tenant_id
        WHERE mapping.new_creator_id <> mapping.old_creator_id
        """
    )
    op.execute(
        """
        UPDATE affiliate_creators AS creator
        SET shop_id = mapping.shop_id
        FROM affiliate_creator_shop_map AS mapping
        WHERE mapping.new_creator_id = creator.id
          AND mapping.tenant_id = creator.tenant_id
        """
    )
    op.execute(
        """
        UPDATE affiliate_creator_metrics AS metric
        SET creator_id = mapping.new_creator_id
        FROM affiliate_creator_shop_map AS mapping
        WHERE mapping.old_creator_id = metric.creator_id
          AND mapping.tenant_id = metric.tenant_id
          AND mapping.shop_id = metric.shop_id
        """
    )
    op.alter_column("affiliate_creators", "shop_id", nullable=False)
    op.alter_column("affiliate_creator_metrics", "shop_id", nullable=False)
    _create_scoped_constraints()
    _replace_indexes()


def _drop_old_constraints() -> None:
    for name in (
        "affiliate_creator_metrics_report_id_tenant_id_fkey",
        "affiliate_creator_metrics_creator_id_tenant_id_fkey",
        "uq_affiliate_creator_metrics_report_creator",
    ):
        constraint_type = "foreignkey" if name.endswith("_fkey") else "unique"
        op.drop_constraint(name, "affiliate_creator_metrics", type_=constraint_type)
    for name in (
        "uq_affiliate_creators_id_tenant",
        "uq_affiliate_creators_tenant_username",
        "uq_affiliate_creators_tenant_open_id",
    ):
        op.drop_constraint(name, "affiliate_creators", type_="unique")
    for name in (
        "uq_affiliate_creator_reports_id_tenant",
        "uq_affiliate_creator_reports_query_revision",
        "uq_affiliate_creator_reports_source_query",
    ):
        op.drop_constraint(name, "affiliate_creator_reports", type_="unique")


def _create_scoped_constraints() -> None:
    op.create_foreign_key(
        "fk_affiliate_creators_shop_tenant",
        "affiliate_creators",
        "shops",
        ["shop_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_affiliate_creators_id_tenant_shop",
        "affiliate_creators",
        ["id", "tenant_id", "shop_id"],
    )
    op.create_unique_constraint(
        "uq_affiliate_creators_shop_username",
        "affiliate_creators",
        ["tenant_id", "shop_id", "username_normalized"],
    )
    op.create_unique_constraint(
        "uq_affiliate_creators_shop_open_id",
        "affiliate_creators",
        ["tenant_id", "shop_id", "creator_open_id"],
    )
    op.create_unique_constraint(
        "uq_affiliate_creator_reports_id_tenant_shop",
        "affiliate_creator_reports",
        ["id", "tenant_id", "shop_id"],
    )
    op.create_unique_constraint(
        "uq_affiliate_creator_reports_shop_query_revision",
        "affiliate_creator_reports",
        ["tenant_id", "shop_id", "query_fingerprint", "revision_no"],
    )
    op.create_unique_constraint(
        "uq_affiliate_creator_reports_shop_source_query",
        "affiliate_creator_reports",
        ["tenant_id", "shop_id", "source_fingerprint", "query_fingerprint"],
    )
    _create_metric_constraints()


def _create_metric_constraints() -> None:
    op.create_foreign_key(
        "fk_affiliate_creator_metrics_shop_tenant",
        "affiliate_creator_metrics",
        "shops",
        ["shop_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_affiliate_creator_metrics_report_tenant_shop",
        "affiliate_creator_metrics",
        "affiliate_creator_reports",
        ["report_id", "tenant_id", "shop_id"],
        ["id", "tenant_id", "shop_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_affiliate_creator_metrics_creator_tenant_shop",
        "affiliate_creator_metrics",
        "affiliate_creators",
        ["creator_id", "tenant_id", "shop_id"],
        ["id", "tenant_id", "shop_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_affiliate_creator_metrics_shop_report_creator",
        "affiliate_creator_metrics",
        ["tenant_id", "shop_id", "report_id", "creator_id"],
    )


def _replace_indexes() -> None:
    for table_name, index_name in (
        ("affiliate_creators", "ix_affiliate_creators_tenant_username"),
        ("affiliate_creator_reports", "ix_affiliate_creator_reports_tenant_period"),
        ("affiliate_creator_metrics", "ix_affiliate_creator_metrics_report_gmv"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.create_index(
        "ix_affiliate_creators_shop_username",
        "affiliate_creators",
        ["tenant_id", "shop_id", "username_normalized"],
    )
    op.create_index(
        "ix_affiliate_creator_reports_shop_period",
        "affiliate_creator_reports",
        ["tenant_id", "shop_id", "period_start", "period_end"],
    )
    op.create_index(
        "ix_affiliate_creator_metrics_report_gmv",
        "affiliate_creator_metrics",
        ["tenant_id", "shop_id", "report_id", "affiliate_gmv_minor"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Shop-scoped affiliate creators cannot be merged without losing revisions."
    )
