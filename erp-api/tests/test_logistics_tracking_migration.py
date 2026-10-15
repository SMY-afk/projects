from pathlib import Path


def test_tracking_migration_has_dedupe_and_polling_contract() -> None:
    migration = Path(
        "migrations/versions/a47e6f8091b3_add_logistics_tracking_events.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "f36e7f8091a2"' in migration
    assert '"logistics_tracking_events"' in migration
    assert "uq_logistics_tracking_events_dedupe" in migration
    assert "tracking_next_poll_at" in migration
    assert "ck_logistics_waybills_tracking_status" in migration
