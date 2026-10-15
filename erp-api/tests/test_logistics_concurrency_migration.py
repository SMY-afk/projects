from importlib import import_module

import sqlalchemy as sa

MIGRATION_MODULE = (
    "migrations.versions.9d0e1f2a3b4c_add_logistics_optimistic_lock_versions"
)
VERSIONED_TABLES = (
    "logistics_tasks",
    "logistics_packages",
    "logistics_carriers",
    "logistics_carrier_services",
    "logistics_carrier_accounts",
    "logistics_waybills",
)


class RecordingOperations:
    def __init__(self) -> None:
        self.added_columns: list[tuple[str, sa.Column]] = []
        self.created_constraints: list[tuple[str, str, tuple[str, ...]]] = []
        self.dropped_columns: list[tuple[str, str]] = []
        self.dropped_constraints: list[tuple[str, str]] = []

    def add_column(self, table: str, column: sa.Column) -> None:
        self.added_columns.append((table, column))

    def create_unique_constraint(
        self, name: str, table: str, columns: list[str]
    ) -> None:
        self.created_constraints.append((name, table, tuple(columns)))

    def drop_column(self, table: str, column: str) -> None:
        self.dropped_columns.append((table, column))

    def drop_constraint(self, name: str, table: str, **kwargs) -> None:
        del kwargs
        self.dropped_constraints.append((name, table))


def test_migration_adds_non_null_version_to_mutable_logistics_aggregates(
    monkeypatch,
) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "8c9d0e1f2a3b"
    assert tuple(table for table, _ in operations.added_columns) == VERSIONED_TABLES
    for _, column in operations.added_columns:
        assert column.name == "version_id"
        assert column.nullable is False
        assert str(column.server_default.arg) == "1"
    assert operations.created_constraints == [
        (
            "uq_logistics_waybills_id_tenant",
            "logistics_waybills",
            ("id", "tenant_id"),
        )
    ]


def test_migration_downgrade_removes_constraint_then_versions(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert operations.dropped_constraints == [
        ("uq_logistics_waybills_id_tenant", "logistics_waybills")
    ]
    assert operations.dropped_columns == [
        (table, "version_id") for table in reversed(VERSIONED_TABLES)
    ]
