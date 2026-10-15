from importlib import import_module

MIGRATION_MODULE = "migrations.versions.f9cd1e3456a8_create_platform_carrier_mappings"


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_indexes: list[tuple[str, str]] = []
        self.executed: list[str] = []
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_tables.append(name)

    def create_index(self, name: str, table: str, *args, **kwargs) -> None:
        del args, kwargs
        self.created_indexes.append((name, table))

    def execute(self, statement) -> None:
        self.executed.append(str(statement))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def test_mapping_migration_creates_table_indexes_and_backfills(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "e8bc0d2345f7"
    assert operations.created_tables == ["logistics_platform_carrier_mappings"]
    assert len(operations.created_indexes) == 5
    assert "ShippingProviderId" in operations.executed[0]


def test_mapping_migration_downgrade_drops_mapping_only(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    assert operations.dropped_tables == ["logistics_platform_carrier_mappings"]
