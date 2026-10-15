from __future__ import annotations

from importlib import import_module

MIGRATION_MODULE = "migrations.versions.5f6a7b8c9d0e_create_finance_domain_tables"


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []
        self.created_constraints: list[tuple[str, str]] = []
        self.dropped_constraints: list[tuple[str, str]] = []

    def create_table(self, name: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_tables.append(name)

    def create_index(self, name: str, table_name: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_indexes.append((name, table_name))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)

    def drop_index(self, name: str, *, table_name: str | None = None) -> None:
        self.dropped_indexes.append((name, table_name))

    def create_unique_constraint(
        self, name: str, table_name: str, *args, **kwargs
    ) -> None:
        del args, kwargs
        self.created_constraints.append((name, table_name))

    def drop_constraint(self, name: str, table_name: str, **kwargs) -> None:
        del kwargs
        self.dropped_constraints.append((name, table_name))


def test_finance_migration_extends_current_head_and_creates_all_tables(
    monkeypatch,
) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.revision == "5f6a7b8c9d0e"
    assert migration.down_revision == "4e5f6a7b8c9d"
    assert operations.created_tables == [
        "finance_statements",
        "finance_payments",
        "finance_payment_statements",
        "finance_transactions",
        "finance_transaction_components",
        "finance_sync_runs",
        "finance_sync_cursors",
    ]
    assert len(operations.created_indexes) >= 12
    assert operations.created_constraints == [
        ("uq_order_lines_id_tenant", "order_lines")
    ]


def test_finance_migration_drops_dependents_before_parents(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert operations.dropped_tables == [
        "finance_sync_cursors",
        "finance_sync_runs",
        "finance_transaction_components",
        "finance_transactions",
        "finance_payment_statements",
        "finance_payments",
        "finance_statements",
    ]
