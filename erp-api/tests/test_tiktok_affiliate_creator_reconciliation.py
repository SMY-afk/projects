from types import SimpleNamespace

from backend.app.services import tiktok_affiliate_creator_export_sync as export_sync


def test_full_identity_sample_replaces_stale_export_aliases() -> None:
    current = SimpleNamespace(username_normalized="creator-current")
    missing = SimpleNamespace(username_normalized="creator-missing")
    stale = SimpleNamespace(username_normalized="creator-old-name")
    sample = SimpleNamespace(records=[current, missing], expected_total=2)

    records, added = export_sync._reconcile_export_records(
        (current, stale), sample, 2
    )

    assert records == (current, missing)
    assert added == 0
