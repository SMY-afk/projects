from pathlib import Path


def test_creator_profile_migration_is_reversible_and_never_backfills_signed_url() -> (
    None
):
    migration = Path(
        "migrations/versions/df36e7f8a9b0_add_sample_creator_profile.py"
    ).read_text(encoding="utf-8")

    for column in (
        "creator_avatar_object_key",
        "creator_avatar_source_hash",
        "creator_avatar_observed_at",
        "creator_profile_snapshot",
        "creator_profile_source_type",
        "creator_profile_observed_at",
    ):
        assert f'"{column}"' in migration
        assert f'op.drop_column("sample_applications", "{column}")' in migration
    assert "creator_avatar_url" not in migration
    assert "raw_payload ->" not in migration
