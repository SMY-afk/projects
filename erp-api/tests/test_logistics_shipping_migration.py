from importlib import import_module

MIGRATION_MODULE = "migrations.versions.8c9d0e1f2a3b_create_logistics_shipping_tables"


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_constraints: list[tuple[str, str]] = []
        self.created_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []
        self.dropped_constraints: list[tuple[str, str]] = []

    def create_table(self, name: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_tables.append(name)

    def create_unique_constraint(self, name: str, table: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_constraints.append((name, table))

    def create_index(self, name: str, table: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_indexes.append((name, table))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)

    def drop_constraint(self, name: str, table: str, **kwargs) -> None:
        del kwargs
        self.dropped_constraints.append((name, table))


def test_shipping_migration_extends_task_head_and_creates_only_shipping_tables(
    monkeypatch,
) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "7b8c9d0e1f2a"
    assert operations.created_tables == [
        "logistics_packages",
        "logistics_package_items",
        "logistics_carriers",
        "logistics_carrier_services",
        "logistics_carrier_accounts",
        "logistics_waybills",
    ]
    assert operations.created_constraints == [
        (
            "uq_logistics_task_items_id_task_tenant",
            "logistics_task_items",
        )
    ]


def test_shipping_migration_drops_dependents_before_parents(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert operations.dropped_tables == [
        "logistics_waybills",
        "logistics_carrier_accounts",
        "logistics_carrier_services",
        "logistics_carriers",
        "logistics_package_items",
        "logistics_packages",
    ]
    assert operations.dropped_constraints == [
        (
            "uq_logistics_task_items_id_task_tenant",
            "logistics_task_items",
        )
    ]
