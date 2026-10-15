from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def _carrier_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["carrier_id", "tenant_id"],
        ["logistics_carriers.id", "logistics_carriers.tenant_id"],
        ondelete="CASCADE",
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return tuple(
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    )


def _index(operations: Any, table: str, column: str) -> None:
    operations.create_index(f"ix_{table}_{column}", table, [column])


def create_carrier_tables(operations: Any) -> None:
    _create_carriers(operations)
    _create_services(operations)
    _create_accounts(operations)
    _create_waybills(operations)


def _create_carriers(operations: Any) -> None:
    operations.create_table(
        "logistics_carriers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tracking_url_template", sa.String(1000)),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_logistics_carriers_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_logistics_carriers_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_logistics_carriers_tenant_code"
        ),
    )
    _index(operations, "logistics_carriers", "tenant_id")


def _create_services(operations: Any) -> None:
    operations.create_table(
        "logistics_carrier_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("carrier_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("service_level", sa.String(64)),
        sa.Column(
            "supported_countries",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "configuration",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _carrier_fk(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_logistics_carrier_services_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "carrier_id",
            "tenant_id",
            name="uq_logistics_carrier_services_id_carrier_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "carrier_id",
            "code",
            name="uq_logistics_carrier_services_tenant_carrier_code",
        ),
    )
    _index(operations, "logistics_carrier_services", "tenant_id")
    _index(operations, "logistics_carrier_services", "carrier_id")


def _create_accounts(operations: Any) -> None:
    operations.create_table(
        "logistics_carrier_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("carrier_id", sa.Uuid(), nullable=False),
        sa.Column("account_name", sa.String(128), nullable=False),
        sa.Column("account_identifier_masked", sa.String(256)),
        sa.Column("auth_type", sa.String(32), nullable=False),
        sa.Column("secret_reference", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _carrier_fk(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'expired')",
            name="ck_logistics_carrier_accounts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "carrier_id",
            "tenant_id",
            name="uq_logistics_carrier_accounts_id_carrier_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "carrier_id",
            "account_name",
            name="uq_logistics_carrier_accounts_tenant_carrier_name",
        ),
    )
    _index(operations, "logistics_carrier_accounts", "tenant_id")
    _index(operations, "logistics_carrier_accounts", "carrier_id")


def _create_waybills(operations: Any) -> None:
    operations.create_table(
        "logistics_waybills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("carrier_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid()),
        sa.Column("account_id", sa.Uuid()),
        sa.Column("waybill_number", sa.String(40), nullable=False),
        sa.Column("external_waybill_id", sa.String(128)),
        sa.Column("tracking_number_masked", sa.String(128)),
        sa.Column("tracking_number_ciphertext", sa.Text()),
        sa.Column("label_url", sa.String(1000)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["package_id", "tenant_id"],
            ["logistics_packages.id", "logistics_packages.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id", "carrier_id", "tenant_id"],
            [
                "logistics_carrier_services.id",
                "logistics_carrier_services.carrier_id",
                "logistics_carrier_services.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "carrier_id", "tenant_id"],
            [
                "logistics_carrier_accounts.id",
                "logistics_carrier_accounts.carrier_id",
                "logistics_carrier_accounts.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('created', 'label_ready', 'shipped', 'in_transit', "
            "'delivered', 'exception', 'cancelled')",
            name="ck_logistics_waybills_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "waybill_number",
            name="uq_logistics_waybills_tenant_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "carrier_id",
            "external_waybill_id",
            name="uq_logistics_waybills_tenant_carrier_external",
        ),
    )
    for column in ("tenant_id", "package_id", "carrier_id"):
        _index(operations, "logistics_waybills", column)
    operations.create_index(
        "uq_logistics_waybills_current_package",
        "logistics_waybills",
        ["tenant_id", "package_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
