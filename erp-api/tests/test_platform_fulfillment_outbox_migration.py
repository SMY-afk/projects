from pathlib import Path


def test_outbox_migration_extends_current_logistics_head() -> None:
    migration = Path(
        "migrations/versions/f36e7f8091a2_add_platform_fulfillment_outbox.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "e25d6e7f8091"' in migration
    assert '"platform_fulfillment_outbox"' in migration
    assert "uq_platform_fulfillment_outbox_tenant_key" in migration
