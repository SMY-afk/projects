from importlib import import_module
from pathlib import Path

MIGRATION_MODULE = (
    "migrations.versions.b1c2d3e4f5a6_create_returns_and_reverse_logistics"
)


def test_returns_migration_extends_current_head_and_has_required_tables() -> None:
    migration = import_module(MIGRATION_MODULE)
    assert migration.down_revision == "a0de2f4567b9"
    source = Path(migration.__file__).read_text(encoding="utf-8")
    for table in ("return_requests", "return_request_items", "return_rmas"):
        assert f'"{table}"' in source
    assert "return_rma_id" in source
    assert "direction" in source
    assert "warehouses" not in source
    assert "inventory_balances" not in source
