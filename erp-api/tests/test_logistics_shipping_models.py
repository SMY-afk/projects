from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import configure_mappers

import erp_api.models
from erp_api.db.base import Base

SHIPPING_TABLES = {
    "logistics_packages",
    "logistics_package_items",
    "logistics_carriers",
    "logistics_carrier_services",
    "logistics_carrier_accounts",
    "logistics_platform_carrier_mappings",
    "logistics_waybills",
}


def _foreign_keys(table_name: str):
    table = Base.metadata.tables[table_name]
    return {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _unique_constraints(table_name: str):
    table = Base.metadata.tables[table_name]
    return {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_shipping_models_register_six_tenant_scoped_tables() -> None:
    assert SHIPPING_TABLES <= Base.metadata.tables.keys()
    assert erp_api.models.LogisticsPackage is not None
    assert erp_api.models.LogisticsCarrierAccount is not None
    assert erp_api.models.LogisticsWaybill is not None


def test_one_task_can_have_multiple_packages_with_same_task_item_integrity() -> None:
    package_fks = _foreign_keys("logistics_packages")
    item_fks = _foreign_keys("logistics_package_items")

    assert (
        ("task_id", "tenant_id"),
        ("logistics_tasks.id", "logistics_tasks.tenant_id"),
    ) in package_fks
    assert (
        ("package_id", "task_id", "tenant_id"),
        (
            "logistics_packages.id",
            "logistics_packages.task_id",
            "logistics_packages.tenant_id",
        ),
    ) in item_fks
    assert (
        ("task_item_id", "task_id", "tenant_id"),
        (
            "logistics_task_items.id",
            "logistics_task_items.task_id",
            "logistics_task_items.tenant_id",
        ),
    ) in item_fks
    assert (
        "uq_logistics_packages_tenant_number",
        ("tenant_id", "package_number"),
    ) in _unique_constraints("logistics_packages")
    assert not any(
        constraint[1] == ("tenant_id", "task_id")
        for constraint in _unique_constraints("logistics_packages")
    )


def test_carrier_services_and_accounts_cannot_cross_tenants() -> None:
    for table_name in (
        "logistics_carrier_services",
        "logistics_carrier_accounts",
    ):
        assert (
            ("carrier_id", "tenant_id"),
            ("logistics_carriers.id", "logistics_carriers.tenant_id"),
        ) in _foreign_keys(table_name)


def test_platform_carrier_mapping_is_tenant_safe_and_service_optional() -> None:
    table_name = "logistics_platform_carrier_mappings"
    foreign_keys = _foreign_keys(table_name)

    assert (
        ("carrier_id", "tenant_id"),
        ("logistics_carriers.id", "logistics_carriers.tenant_id"),
    ) in foreign_keys
    assert (
        ("service_id", "carrier_id", "tenant_id"),
        (
            "logistics_carrier_services.id",
            "logistics_carrier_services.carrier_id",
            "logistics_carrier_services.tenant_id",
        ),
    ) in foreign_keys
    assert Base.metadata.tables[table_name].columns["service_id"].nullable is True
    assert (
        "uq_logistics_platform_carrier_mappings_id_tenant",
        ("id", "tenant_id"),
    ) in _unique_constraints(table_name)


def test_carrier_declares_adapter_key_for_incremental_provider_integration() -> None:
    column = Base.metadata.tables["logistics_carriers"].columns["adapter_key"]

    assert column.nullable is False
    assert column.server_default.arg == "manual"


def test_carrier_accounts_never_store_plaintext_credentials() -> None:
    columns = set(Base.metadata.tables["logistics_carrier_accounts"].columns.keys())

    assert "account_identifier_masked" in columns
    assert "secret_reference" in columns
    assert {
        "password",
        "api_key",
        "access_token",
        "secret",
        "credentials",
    }.isdisjoint(columns)


def test_waybill_links_package_carrier_service_and_account_inside_tenant() -> None:
    foreign_keys = _foreign_keys("logistics_waybills")

    assert (
        ("package_id", "tenant_id"),
        ("logistics_packages.id", "logistics_packages.tenant_id"),
    ) in foreign_keys
    assert (
        ("carrier_id", "tenant_id"),
        ("logistics_carriers.id", "logistics_carriers.tenant_id"),
    ) in foreign_keys
    assert (
        ("service_id", "carrier_id", "tenant_id"),
        (
            "logistics_carrier_services.id",
            "logistics_carrier_services.carrier_id",
            "logistics_carrier_services.tenant_id",
        ),
    ) in foreign_keys
    assert (
        ("account_id", "carrier_id", "tenant_id"),
        (
            "logistics_carrier_accounts.id",
            "logistics_carrier_accounts.carrier_id",
            "logistics_carrier_accounts.tenant_id",
        ),
    ) in foreign_keys
    indexes = {
        index.name: index
        for index in Base.metadata.tables["logistics_waybills"].indexes
        if isinstance(index, Index)
    }
    assert indexes["uq_logistics_waybills_current_package"].unique is True


def test_shipping_tables_have_no_warehouse_or_inventory_links() -> None:
    forbidden = {
        "warehouse_id",
        "location_id",
        "inventory_id",
        "stock_quantity",
        "reserved_quantity",
    }
    for table_name in SHIPPING_TABLES:
        assert forbidden.isdisjoint(Base.metadata.tables[table_name].columns.keys())


def test_mutable_logistics_aggregates_use_integer_optimistic_lock_versions() -> None:
    configure_mappers()
    model_names = (
        "LogisticsTask",
        "LogisticsPackage",
        "LogisticsCarrier",
        "LogisticsCarrierService",
        "LogisticsCarrierAccount",
        "LogisticsPlatformCarrierMapping",
        "LogisticsWaybill",
    )

    for model_name in model_names:
        model = getattr(erp_api.models, model_name)
        column = model.__table__.columns["version_id"]
        assert column.nullable is False
        assert model.__mapper__.version_id_col is column


def test_logistics_quantities_have_database_check_constraints() -> None:
    expected = {
        "logistics_task_items": "ck_logistics_task_items_quantity_progress",
        "logistics_package_items": "ck_logistics_package_items_quantity",
        "logistics_task_reviews": "ck_logistics_task_reviews_quantities",
    }

    for table_name, constraint_name in expected.items():
        checks = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert constraint_name in checks


def test_waybill_has_tenant_identity_unique_constraint() -> None:
    assert (
        "uq_logistics_waybills_id_tenant",
        ("id", "tenant_id"),
    ) in _unique_constraints("logistics_waybills")


def test_platform_carrier_mapping_is_store_scoped_and_separates_provider_id() -> None:
    table = Base.metadata.tables["logistics_platform_carrier_mappings"]

    assert {
        "store_id",
        "platform_carrier_id",
        "platform_carrier_code",
        "delivery_option_id",
        "raw_payload",
    }.issubset(table.columns.keys())
    assert (
        ("store_id", "tenant_id"),
        ("shops.id", "shops.tenant_id"),
    ) in _foreign_keys("logistics_platform_carrier_mappings")
    assert table.columns["store_id"].nullable is False
    assert table.columns["platform_carrier_id"].nullable is False
