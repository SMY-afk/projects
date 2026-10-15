from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from erp_api.services.creator_sync_state import (
    creator_data_hash,
    should_sync_creator,
)
from tests.test_affiliate_creator_persistence import _page, _query


def test_creator_hash_changes_only_when_creator_data_changes() -> None:
    record = _page(_query()).records[0]

    first = creator_data_hash(record)
    second = creator_data_hash(record)

    assert first == second
    assert len(first) == 64


def test_incremental_sync_selects_new_changed_failed_or_stale_creators() -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    fresh = now - timedelta(hours=1)
    stale = now - timedelta(hours=25)

    assert should_sync_creator(None, "hash", stale_before=now) is True
    assert (
        should_sync_creator(
            SimpleNamespace(
                data_hash="old", last_sync_at=fresh, sync_status="succeeded"
            ),
            "new",
            stale_before=now - timedelta(hours=24),
        )
        is True
    )
    assert (
        should_sync_creator(
            SimpleNamespace(
                data_hash="hash", last_sync_at=stale, sync_status="succeeded"
            ),
            "hash",
            stale_before=now - timedelta(hours=24),
        )
        is True
    )
    assert (
        should_sync_creator(
            SimpleNamespace(data_hash="hash", last_sync_at=fresh, sync_status="failed"),
            "hash",
            stale_before=now - timedelta(hours=24),
        )
        is True
    )
    assert (
        should_sync_creator(
            SimpleNamespace(
                data_hash="hash", last_sync_at=fresh, sync_status="succeeded"
            ),
            "hash",
            stale_before=now - timedelta(hours=24),
        )
        is False
    )
