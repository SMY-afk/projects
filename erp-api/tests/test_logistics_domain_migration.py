from importlib import import_module

MIGRATION_MODULE = "migrations.versions.7b8c9d0e1f2a_create_logistics_task_tables"


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_tables.append(name)

    def create_index(self, name: str, table_name: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_indexes.append((name, table_name))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def test_logistics_migration_extends_permission_head_and_creates_only_domain_tables(
    monkeypatch,
) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "6a7b8c9d0e1f"
    assert operations.created_tables == [
        "logistics_tasks",
        "logistics_task_items",
        "logistics_task_operations",
        "logistics_task_reviews",
    ]
    assert all(
        term not in table
        for table in operations.created_tables
        for term in ("warehouse", "inventory", "transfer")
    )


def test_logistics_migration_drops_dependents_before_tasks(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert operations.dropped_tables == [
        "logistics_task_reviews",
        "logistics_task_operations",
        "logistics_task_items",
        "logistics_tasks",
    ]
