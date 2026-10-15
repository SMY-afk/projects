from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.sample_bd_invitation_ai_priority import (
    AiInvitationCheckWindow,
    AiInvitationSnapshot,
    AiInvitationSnapshotStore,
)


class _Redis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value


class _Sheet:
    def __init__(self, creator_ids):
        self.creator_ids = frozenset(creator_ids)

    async def list_invitation_rows(self):
        return tuple((creator, "2026/09/24 17:59") for creator in self.creator_ids)


@pytest.mark.asyncio
async def test_snapshot_round_trip_is_scoped_to_online_sheet() -> None:
    redis = _Redis()
    store = AiInvitationSnapshotStore(
        redis, spreadsheet_token="sheet-one", sheet_id="tab-one"
    )
    other = AiInvitationSnapshotStore(
        redis, spreadsheet_token="sheet-two", sheet_id="tab-one"
    )
    snapshot = AiInvitationSnapshot(
        datetime(2026, 9, 24, 10, tzinfo=UTC), frozenset({"a", "b"})
    )

    await store.save(snapshot)

    assert await store.load() == snapshot
    assert await other.load() is None
    assert "sheet-one" not in store.key


@pytest.mark.asyncio
async def test_corrupt_snapshot_stops_instead_of_guessing_order() -> None:
    redis = _Redis()
    store = AiInvitationSnapshotStore(redis, spreadsheet_token="s", sheet_id="t")
    redis.values[store.key] = '{"observed_at":"bad","creator_ids":[]}'

    with pytest.raises(RuntimeError, match="snapshot is invalid"):
        await store.load()


@pytest.mark.asyncio
async def test_new_ai_id_and_bd_submission_must_share_recent_check_interval() -> None:
    redis = _Redis()
    store = AiInvitationSnapshotStore(redis, spreadsheet_token="s", sheet_id="t")
    first_time = datetime(2026, 9, 24, 10, tzinfo=UTC)
    await store.save(AiInvitationSnapshot(first_time, frozenset({"old"})))
    window = await AiInvitationCheckWindow.capture(
        store, _Sheet({"old", "new"}), first_time + timedelta(seconds=60)
    )

    assert window.both_new("new", first_time + timedelta(seconds=30))
    assert not window.both_new("old", first_time + timedelta(seconds=30))
    assert not window.both_new("new", first_time - timedelta(seconds=1))

    late = await AiInvitationCheckWindow.capture(
        store, _Sheet({"old", "new"}), first_time + timedelta(minutes=3)
    )
    assert not late.both_new("new", first_time + timedelta(seconds=30))
