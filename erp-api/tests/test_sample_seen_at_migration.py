from pathlib import Path


def test_seen_at_migration_backfills_and_supports_downgrade() -> None:
    migration = Path(
        "migrations/versions/ac03b4c5d6e7_add_sample_seen_timestamps.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "9bf2a3b4c5d6"' in migration
    assert "op.add_column(" in migration
    assert migration.count('"sample_applications"') >= 6
    assert '"first_seen_at"' in migration
    assert '"last_seen_at"' in migration
    assert "UPDATE sample_applications" in migration
    assert 'op.drop_column("sample_applications", "last_seen_at")' in migration
    assert 'op.drop_column("sample_applications", "first_seen_at")' in migration
