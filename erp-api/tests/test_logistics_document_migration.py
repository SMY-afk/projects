from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "e25d6e7f8091_add_logistics_documents.py"
)


def test_document_migration_extends_adapter_head_without_inventory_scope() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "d14c5d6e7f80"' in source
    for value in ("shipping_label", "carrier_invoice", "return_proof"):
        assert value in source
    assert "logistics_waybills.id" in source
    assert not any(value in source for value in ("warehouse", "inventory", "stock"))
