from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from erp_api.workers.logistics_status_monitor import pick_tracking_batch


def test_monitor_rotates_oldest_active_snapshots_and_does_not_starve_active_orders():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            id=uuid4(), external_status="AWAITING_COLLECTION", placed_at=now
        )
    ]
    recent, failed = uuid4(), uuid4()
    rows += [
        SimpleNamespace(id=value, external_status="IN_TRANSIT", placed_at=now)
        for value in [recent, failed]
    ]
    rows += [
        SimpleNamespace(
            id=uuid4(), external_status="COMPLETED", placed_at=now - timedelta(days=1)
        )
        for _ in range(100)
    ]
    cached = {recent: {"checkedAt": now.isoformat(), "firstLocationAt": None, "shippedAt": None, "ruleVersion": 2}}
    selected = pick_tracking_batch(
        rows, cached, {failed: now.timestamp() + 300}, now.timestamp()
    )
    assert rows[0].id in selected
    assert recent not in selected
    assert failed not in selected
    assert len(selected) == 4


def test_legacy_snapshot_is_rechecked_for_new_physical_evidence():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    row = SimpleNamespace(
        id=uuid4(), external_status="AWAITING_COLLECTION", placed_at=now
    )
    assert pick_tracking_batch(
        [row], {row.id: {"checkedAt": now.isoformat()}}, {}, now.timestamp()
    ) == [row.id]


def test_warning_export_warming_reuses_existing_batch_and_respects_failed_query_backoff():
    now = datetime(2026, 10, 13, tzinfo=UTC)
    identifier = uuid4()
    row = SimpleNamespace(id=identifier, external_status="AWAITING_COLLECTION", placed_at=now)
    cache = {identifier: {"checkedAt": now.isoformat(), "firstLocationAt": None, "shippedAt": None, "ruleVersion": 2}}
    assert pick_tracking_batch([row], cache, {}, now.timestamp(), warm_ids={identifier}) == [identifier]
    assert pick_tracking_batch([row], cache, {identifier: now.timestamp() + 300},
                               now.timestamp(), warm_ids={identifier}) == []
