from pathlib import Path


def test_source_capture_migration_is_scoped_and_reversible() -> None:
    migration = Path(
        "migrations/versions/bd14c5d6e7f8_add_sample_source_capture.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "ac03b4c5d6e7"' in migration
    assert 'sa.Column("source_capture_id", sa.Uuid(), nullable=True)' in migration
    assert '"source_capture_id", "tenant_id", "shop_id"' in migration
    assert '"id", "tenant_id", "shop_id"' in migration
    assert 'ondelete="RESTRICT"' in migration
    assert 'op.drop_column("sample_applications", "source_capture_id")' in migration
