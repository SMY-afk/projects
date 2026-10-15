from importlib import import_module

import sqlalchemy as sa
from sqlalchemy import CheckConstraint

from erp_api.db.base import Base
from erp_api.models import LogisticsTaskItem

MIGRATION_MODULE = "migrations.versions.bf2a3b4c5d6e_add_logistics_task_quantities"


class RecordingOperations:
    def __init__(self) -> None:
        self.added_columns: list[tuple[str, str]] = []
        self.altered_columns: list[tuple[str, str, dict[str, object]]] = []
        self.created_checks: list[tuple[str, str, str]] = []
        self.dropped_columns: list[tuple[str, str]] = []
        self.dropped_constraints: list[tuple[str, str]] = []
        self.executed: list[str] = []

    def add_column(self, table: str, column: sa.Column) -> None:
        self.added_columns.append((table, str(column.name)))

    def alter_column(self, table: str, column: str, **kwargs) -> None:
        self.altered_columns.append((table, column, kwargs))

    def create_check_constraint(self, name: str, table: str, condition: str) -> None:
        self.created_checks.append((name, table, condition))

    def drop_column(self, table: str, column: str) -> None:
        self.dropped_columns.append((table, column))

    def drop_constraint(self, name: str, table: str, **kwargs) -> None:
        del kwargs
        self.dropped_constraints.append((name, table))

    def execute(self, statement) -> None:
        self.executed.append(str(statement))


def test_task_items_only_maintain_plan_pack_and_ship_quantities() -> None:
    table = Base.metadata.tables["logistics_task_items"]
    assert LogisticsTaskItem.__table__ is table
    columns = set(table.columns.keys())

    assert {"planned_quantity", "packed_quantity", "shipped_quantity"} <= columns
    assert {
        "quantity",
        "reserved_quantity",
        "allocated_quantity",
        "stock_quantity",
        "inventory_id",
    }.isdisjoint(columns)
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "planned_quantity > 0" in checks["ck_logistics_task_items_planned_quantity"]
    progress = checks["ck_logistics_task_items_quantity_progress"]
    assert "shipped_quantity >= 0" in progress
    assert "shipped_quantity <= packed_quantity" in progress
    assert "packed_quantity <= planned_quantity" in progress


def test_quantity_migration_renames_plan_and_backfills_package_progress(
    monkeypatch,
) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "ae1f2a3b4c5d"
    assert operations.altered_columns[0][1:] == (
        "quantity",
        {"new_column_name": "planned_quantity"},
    )
    assert operations.added_columns == [
        ("logistics_task_items", "packed_quantity"),
        ("logistics_task_items", "shipped_quantity"),
    ]
    backfill_sql = " ".join(operations.executed)
    assert "logistics_package_items" in backfill_sql
    assert "packed_quantity" in backfill_sql
    assert "shipped_quantity" in backfill_sql


def test_quantity_migration_has_a_bounded_downgrade(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert operations.dropped_columns == [
        ("logistics_task_items", "shipped_quantity"),
        ("logistics_task_items", "packed_quantity"),
    ]
    assert operations.altered_columns[-1][1:] == (
        "planned_quantity",
        {"new_column_name": "quantity"},
    )
