from pathlib import Path


def test_exception_migration_follows_tracking_and_keeps_active_dedupe() -> None:
    migration = Path(
        "migrations/versions/b58f7a9012c4_add_logistics_exceptions.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "a47e6f8091b3"' in migration
    assert '"logistics_exceptions"' in migration
    assert '"logistics_exception_actions"' in migration
    assert "uq_logistics_exceptions_active_fingerprint" in migration
    assert "status != 'closed'" in migration


def test_exception_event_link_uses_tenant_composite_foreign_key() -> None:
    migration = Path(
        "migrations/versions/c69a8b0123d5_link_logistics_exception_event.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "b58f7a9012c4"' in migration
    assert "uq_logistics_tracking_events_id_tenant" in migration
    assert "fk_logistics_exceptions_source_event_tenant" in migration
    assert '["source_event_id", "tenant_id"]' in migration
