import importlib
from pathlib import Path

from sqlalchemy import CheckConstraint

from erp_api.db.base import Base


def test_task_center_columns_and_filters_exclude_warehouse() -> None:
    table = Base.metadata.tables["logistics_tasks"]

    assert {"shop_id", "priority"}.issubset(table.columns.keys())
    assert "warehouse_id" not in table.columns
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_logistics_tasks_priority" in checks
    assert set(checks["ck_logistics_tasks_priority"].split("'")) >= {
        "low",
        "normal",
        "high",
        "urgent",
    }
    indexes = {index.name: tuple(index.columns.keys()) for index in table.indexes}
    assert indexes["ix_logistics_tasks_center_filter"] == (
        "tenant_id",
        "shop_id",
        "source_type",
        "status",
        "priority",
        "created_at",
    )


def test_package_has_explicit_sealing_audit_without_inventory_fields() -> None:
    table = Base.metadata.tables["logistics_packages"]

    assert {"sealed_by_user_id", "sealed_at"}.issubset(table.columns.keys())
    assert not {"warehouse_id", "location_id", "wave_id", "inventory_id"} & set(
        table.columns.keys()
    )
    checks = {constraint.name for constraint in table.constraints}
    assert "ck_logistics_packages_sealing_audit" in checks


def test_center_and_sealing_migration_extends_current_head() -> None:
    migration = importlib.import_module(
        "migrations.versions.c03b4c5d6e7f_add_logistics_center_and_sealing"
    )
    source = Path(migration.__file__).read_text(encoding="utf-8")

    assert migration.down_revision == "bf2a3b4c5d6e"
    assert "shop_id" in source
    assert "priority" in source
    assert "sealed_by_user_id" in source
    assert "sealed_at" in source
    assert "warehouse" not in source
