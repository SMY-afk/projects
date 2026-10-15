from importlib import import_module
from pathlib import Path

MIGRATION_MODULE = "migrations.versions.c2d3e4f5a6b7_add_platform_returns_sync"


def test_platform_returns_migration_extends_returns_head_and_is_reversible() -> None:
    migration = import_module(MIGRATION_MODULE)
    assert migration.down_revision == "b1c2d3e4f5a6"
    source = Path(migration.__file__).read_text(encoding="utf-8")
    for field in (
        "source",
        "platform_return_id",
        "platform_status",
        "platform_return_line_id",
        "raw_payload",
    ):
        assert field in source
    assert "def downgrade" in source
    assert "warehouses" not in source
    assert "inventory" not in source
