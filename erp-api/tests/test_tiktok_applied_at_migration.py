from pathlib import Path


def test_tiktok_applied_at_migration_is_nullable_and_reversible() -> None:
    migration = Path(
        "migrations/versions/e047f8a9b0c1_add_sample_tiktok_applied_at.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "df36e7f8a9b0"' in migration
    assert '"tiktok_applied_at"' in migration
    assert "sa.DateTime(timezone=True)" in migration
    assert "nullable=True" in migration
    assert 'op.drop_column("sample_applications", "tiktok_applied_at")' in migration
