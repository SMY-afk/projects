import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.routers import data as data_router
from erp_api.services.analytics_read_repository import StoredAnalyticsContent
from erp_api.services.video_ranges import resolve_video_range

SHOP_TIMEZONE = "America/Los_Angeles"
NOW = datetime(2026, 8, 19, 18, 45, tzinfo=UTC)


class WindowAwareContentRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def shop_exists(self, tenant_id, shop_id):
        return True

    async def get_shop_timezone(self, tenant_id, shop_id):
        return SHOP_TIMEZONE

    async def list_content(self, tenant_id, shop_id, **kwargs):
        self.calls.append(kwargs)
        start = kwargs.get("window_start")
        views = 308 if start == datetime(2026, 8, 19, 7, tzinfo=UTC) else 42
        return [
            StoredAnalyticsContent(
                platform_external_id="video-1",
                fields={"views": views},
                source_status="published",
                status="published",
                source_updated_at=NOW,
                observed_at=NOW,
            )
        ]

    async def get_video_window_state(self, tenant_id, shop_id, **kwargs):
        return None


class EmptyWindowContentRepository(WindowAwareContentRepository):
    async def list_content(self, tenant_id, shop_id, **kwargs):
        self.calls.append(kwargs)
        return []


class MaterializedEmptyWindowRepository(EmptyWindowContentRepository):
    async def get_video_window_state(self, tenant_id, shop_id, **kwargs):
        return SimpleNamespace(
            finished_at=NOW,
            latest_available_date=date(2026, 8, 17),
        )


def _resolve_range(
    preset: str,
    *,
    custom_from: date | None = None,
    custom_to: date | None = None,
):
    return resolve_video_range(
        preset=preset,
        shop_timezone=SHOP_TIMEZONE,
        now=NOW,
        custom_from=custom_from,
        custom_to=custom_to,
    )


@pytest.mark.parametrize(
    ("preset", "expected_start", "expected_end", "is_partial"),
    [
        (
            "today",
            datetime(2026, 8, 19, 7, tzinfo=UTC),
            datetime(2026, 8, 20, 7, tzinfo=UTC),
            True,
        ),
        (
            "last7d",
            datetime(2026, 8, 13, 7, tzinfo=UTC),
            datetime(2026, 8, 20, 7, tzinfo=UTC),
            True,
        ),
        (
            "last30d",
            datetime(2026, 7, 21, 7, tzinfo=UTC),
            datetime(2026, 8, 20, 7, tzinfo=UTC),
            True,
        ),
    ],
)
def test_video_presets_use_shop_local_calendar_days(
    preset: str,
    expected_start: datetime,
    expected_end: datetime,
    is_partial: bool,
) -> None:
    resolved = _resolve_range(preset)

    assert resolved.window_start == expected_start
    assert resolved.window_end == expected_end
    assert resolved.is_partial is is_partial


def test_custom_video_range_includes_both_selected_dates() -> None:
    resolved = _resolve_range(
        "custom",
        custom_from=date(2026, 8, 1),
        custom_to=date(2026, 8, 15),
    )

    assert resolved.window_start == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert resolved.window_end == datetime(2026, 8, 16, 7, tzinfo=UTC)
    assert resolved.is_partial is False
    assert resolved.platform_start_date == date(2026, 8, 1)
    assert resolved.platform_end_date == date(2026, 8, 16)


def test_video_range_uses_local_midnights_across_daylight_saving_time() -> None:
    resolved = resolve_video_range(
        preset="custom",
        shop_timezone=SHOP_TIMEZONE,
        now=datetime(2026, 3, 10, 18, tzinfo=UTC),
        custom_from=date(2026, 3, 7),
        custom_to=date(2026, 3, 9),
    )

    assert resolved.window_start == datetime(2026, 3, 7, 8, tzinfo=UTC)
    assert resolved.window_end == datetime(2026, 3, 10, 7, tzinfo=UTC)
    assert (resolved.window_end - resolved.window_start).total_seconds() == 71 * 3600


def test_video_api_window_requires_utc_instants() -> None:
    with pytest.raises(ValueError, match="from must use UTC"):
        data_router.validate_video_window(
            window_start=datetime(
                2026,
                8,
                19,
                15,
                tzinfo=timezone(timedelta(hours=8)),
            ),
            window_end=datetime(2026, 8, 20, 7, tzinfo=UTC),
            shop_timezone=SHOP_TIMEZONE,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("custom_from", "custom_to", "message"),
    [
        (
            date(2026, 8, 1),
            date(2026, 8, 20),
            "future dates",
        ),
        (
            date(2026, 8, 10),
            date(2026, 8, 9),
            "start date must not be after end date",
        ),
        (
            date(2026, 7, 20),
            date(2026, 8, 19),
            "must not exceed 30 days",
        ),
    ],
)
def test_custom_video_range_rejects_invalid_dates(
    custom_from: date,
    custom_to: date,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _resolve_range(
            "custom",
            custom_from=custom_from,
            custom_to=custom_to,
        )


def test_video_route_returns_metrics_for_the_requested_window() -> None:
    repository = WindowAwareContentRepository()
    tenant_id, shop_id = uuid4(), uuid4()
    request = _request()

    async def fetch(window_start: datetime, window_end: datetime):
        return await data_router.list_content(
            request=request,
            shop_id=shop_id,
            from_=window_start,
            to=window_end,
            currency="USD",
            account_type="ALL",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=repository,
        )

    today = asyncio.run(
        fetch(
            datetime(2026, 8, 19, 7, tzinfo=UTC),
            datetime(2026, 8, 20, 7, tzinfo=UTC),
        )
    )
    previous_day = asyncio.run(
        fetch(
            datetime(2026, 8, 18, 7, tzinfo=UTC),
            datetime(2026, 8, 19, 7, tzinfo=UTC),
        )
    )

    assert today.data[0].fields["views"] == 308
    assert previous_day.data[0].fields["views"] == 42
    assert repository.calls[0]["window_start"] != repository.calls[1]["window_start"]
    assert today.range.windowStart == datetime(2026, 8, 19, 7, tzinfo=UTC)
    assert today.range.windowEnd == datetime(2026, 8, 20, 7, tzinfo=UTC)
    assert today.range.shopTimezone == SHOP_TIMEZONE
    assert today.range.isPartial is True


def test_video_route_marks_an_unmaterialized_window_unavailable() -> None:
    repository = EmptyWindowContentRepository()

    response = asyncio.run(
        data_router.list_content(
            request=_request(),
            shop_id=uuid4(),
            from_=datetime(2026, 8, 13, 7, tzinfo=UTC),
            to=datetime(2026, 8, 20, 7, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            session=SimpleNamespace(tenant_id=uuid4()),
            _=SimpleNamespace(),
            repository=repository,
        )
    )

    assert response.data == []
    assert response.freshness.isStale is True
    assert response.errors[0].code == "data_unavailable"
    assert response.errors[0].action == "resync"
    assert response.errors[0].message == (
        "No data is available for the requested time range."
    )
    assert response.range.windowStart == datetime(2026, 8, 13, 7, tzinfo=UTC)


def test_video_route_returns_latest_tiktok_date_for_a_materialized_empty_window() -> (
    None
):
    response = asyncio.run(
        data_router.list_content(
            request=_request(),
            shop_id=uuid4(),
            from_=datetime(2026, 8, 19, 7, tzinfo=UTC),
            to=datetime(2026, 8, 20, 7, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            session=SimpleNamespace(tenant_id=uuid4()),
            _=SimpleNamespace(),
            repository=MaterializedEmptyWindowRepository(),
        )
    )

    assert response.data == []
    assert response.freshness.isStale is False
    assert response.freshness.asOf == NOW
    assert response.errors == []
    assert response.range.latestAvailableDate == date(2026, 8, 17)


def _request():
    return SimpleNamespace(
        url=SimpleNamespace(path="/api/data/videos"),
        app=SimpleNamespace(state=SimpleNamespace(clock=lambda: NOW)),
    )
