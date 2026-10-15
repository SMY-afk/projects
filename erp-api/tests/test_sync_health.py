import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from erp_api.main import create_app
from erp_api.routers.sync_health import list_sync_health
from erp_api.services.sync_health_repository import (
    SyncCursorSample,
    SyncHealthResult,
    SyncRunSample,
    calculate_sync_health,
)


class FakeHealthRepository:
    def __init__(self, row: SyncHealthResult) -> None:
        self.row = row

    async def list_health(self, tenant_id, *, shop_id=None):
        return [self.row]


def test_sync_health_reports_failures_rate_limits_dead_letters_and_gaps() -> None:
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    last_success = now - timedelta(hours=50)
    runs = [
        SyncRunSample("succeeded", None),
        SyncRunSample("failed", "rate_limited"),
        SyncRunSample("dead_letter", "rate_limited"),
        SyncRunSample("retry_wait", "timeout"),
    ]

    result = calculate_sync_health(
        shop_id=uuid4(),
        shop_name="Test Shop",
        resource_type="video",
        runs=runs,
        cursor=SyncCursorSample(last_success_at=last_success),
        now=now,
        window_hours=168,
        expected_interval_minutes=1440,
    )

    assert result.last_success_at == last_success
    assert result.delay_seconds == 180_000
    assert result.failure_rate == 0.6667
    assert result.rate_limit_429_count == 2
    assert result.dead_letter_count == 1
    assert result.data_gap_count == 2
    assert result.status == "critical"


def test_sync_health_uses_newer_successful_run_for_explicit_window_freshness() -> None:
    now = datetime(2026, 9, 7, 20, 12, tzinfo=UTC)
    cursor_success = now - timedelta(days=14, hours=21)
    explicit_run_success = now - timedelta(hours=2)

    result = calculate_sync_health(
        shop_id=uuid4(),
        shop_name="Test Shop",
        resource_type="video",
        runs=[
            SyncRunSample(
                "succeeded",
                None,
                finished_at=explicit_run_success,
            )
        ],
        cursor=SyncCursorSample(last_success_at=cursor_success),
        now=now,
        window_hours=168,
        expected_interval_minutes=1440,
    )

    assert result.last_success_at == explicit_run_success
    assert result.delay_seconds == 7_200
    assert result.data_gap_count == 0
    assert result.status == "healthy"


def test_sync_health_marks_never_synced_entity_critical_without_inventing_a_rate() -> (
    None
):
    result = calculate_sync_health(
        shop_id=uuid4(),
        shop_name="New Shop",
        resource_type="live",
        runs=[],
        cursor=None,
        now=datetime(2026, 8, 19, 8, tzinfo=UTC),
        window_hours=168,
        expected_interval_minutes=1440,
    )

    assert result.last_success_at is None
    assert result.delay_seconds is None
    assert result.failure_rate is None
    assert result.data_gap_count == 1
    assert result.status == "critical"


def test_sync_health_route_exposes_tenant_scoped_metrics() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    row = SyncHealthResult(
        shop_id=shop_id,
        shop_name="Test Shop",
        resource_type="video",
        status="healthy",
        last_success_at=datetime(2026, 8, 19, 8, tzinfo=UTC),
        delay_seconds=30,
        failure_rate=0,
        rate_limit_429_count=0,
        dead_letter_count=0,
        data_gap_count=0,
        total_run_count=7,
        successful_run_count=7,
        window_hours=168,
    )

    response = asyncio.run(
        list_sync_health(
            shop_id=shop_id,
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=FakeHealthRepository(row),
        )
    )

    assert response[0].shopId == shop_id
    assert response[0].failureRate == 0
    assert response[0].windowHours == 168


def test_sync_health_route_is_registered() -> None:
    assert "/api/sync-health" in {route.path for route in create_app().routes}
