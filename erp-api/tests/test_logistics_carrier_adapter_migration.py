from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "d14c5d6e7f80_add_carrier_adapter_key.py"
)


def test_carrier_adapter_migration_extends_current_logistics_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "c03b4c5d6e7f"' in source
    assert '"logistics_carriers"' in source
    assert '"adapter_key"' in source
    assert 'server_default="manual"' in source
    assert not any(term in source for term in ("warehouse", "inventory", "transfer"))
