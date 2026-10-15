from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_summary import video_summary_from_rows
from erp_api.services.affiliate_daily_queries import (
    split_bounded_queries,
    split_daily_queries,
)
from erp_api.services.affiliate_video_window_aggregation import (
    aggregate_video_rows,
    split_video_query,
)


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=date(2026, 6, 26),
        window_end=date(2026, 8, 25),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_sixty_day_operator_window_uses_thirty_day_exports() -> None:
    chunks = split_video_query(_query())

    assert [(item.window_start, item.window_end) for item in chunks] == [
        (date(2026, 6, 26), date(2026, 7, 25)),
        (date(2026, 7, 26), date(2026, 8, 24)),
        (date(2026, 8, 25), date(2026, 8, 25)),
    ]


def test_thirty_day_operator_window_uses_one_export() -> None:
    query = replace(
        _query(),
        window_start=date(2026, 7, 27),
        window_end=date(2026, 8, 25),
    )

    assert [
        (item.window_start, item.window_end) for item in split_video_query(query)
    ] == [
        (date(2026, 7, 27), date(2026, 8, 25)),
    ]


def test_creator_window_can_use_the_same_thirty_day_api_chunks() -> None:
    query = replace(_query(), resource=AffiliateCenterResource.CREATORS)

    assert [
        (item.window_start, item.window_end)
        for item in split_bounded_queries(query, max_days=30)
    ] == [
        (date(2026, 6, 26), date(2026, 7, 25)),
        (date(2026, 7, 26), date(2026, 8, 24)),
        (date(2026, 8, 25), date(2026, 8, 25)),
    ]


def test_arbitrary_window_can_be_composed_from_daily_snapshots() -> None:
    query = replace(
        _query(),
        window_start=date(2026, 7, 29),
        window_end=date(2026, 8, 2),
    )

    assert [
        (item.window_start, item.window_end) for item in split_daily_queries(query)
    ] == [
        (date(2026, 7, 29), date(2026, 7, 29)),
        (date(2026, 7, 30), date(2026, 7, 30)),
        (date(2026, 7, 31), date(2026, 7, 31)),
        (date(2026, 8, 1), date(2026, 8, 1)),
        (date(2026, 8, 2), date(2026, 8, 2)),
    ]


def test_window_over_export_limit_is_split() -> None:
    query = replace(
        _query(),
        window_start=date(2026, 6, 25),
        window_end=date(2026, 8, 25),
    )

    assert [
        (item.window_start, item.window_end) for item in split_video_query(query)
    ] == [
        (date(2026, 6, 25), date(2026, 7, 24)),
        (date(2026, 7, 25), date(2026, 8, 23)),
        (date(2026, 8, 24), date(2026, 8, 25)),
    ]


def test_video_rows_sum_additive_metrics_and_recompute_rates() -> None:
    captured = datetime(2026, 8, 27, tzinfo=UTC)
    first = SimpleNamespace(
        platform_video_id="video-1",
        metrics={
            "gmvMinor": 100,
            "orderCount": 1,
            "productImpressions": 100,
            "productClicks": 10,
            "views": 200,
            "likes": 10,
            "comments": 2,
            "shares": 1,
            "finishRate": "0.5",
        },
        source_updated_at=captured,
        captured_at=captured,
    )
    second = SimpleNamespace(
        platform_video_id="video-1",
        metrics={
            "gmvMinor": 500,
            "orderCount": 2,
            "productImpressions": 300,
            "productClicks": 30,
            "views": 600,
            "likes": 30,
            "comments": 4,
            "shares": 3,
            "finishRate": "0.25",
        },
        source_updated_at=captured,
        captured_at=captured,
    )
    content = SimpleNamespace(fields={"title": "Video"})

    rows = aggregate_video_rows([(first, content), (second, content)])

    snapshot, selected_content = rows[0]
    assert selected_content is content
    assert snapshot.metrics["gmvMinor"] == 600
    assert snapshot.metrics["orderCount"] == 3
    assert snapshot.metrics["views"] == 800
    assert snapshot.metrics["averageOrderValueMinor"] == 200
    assert snapshot.metrics["productClickThroughRate"] == "0.1"
    assert snapshot.metrics["engagementRate"] == "0.0625"
    assert snapshot.metrics["finishRate"] == "0.3125"


def test_video_summary_totals_the_whole_selected_window() -> None:
    captured = datetime(2026, 8, 27, tzinfo=UTC)
    rows = [
        (
            SimpleNamespace(
                platform_video_id=f"video-{index}",
                metrics=metrics,
                source_updated_at=captured,
                captured_at=captured,
            ),
            SimpleNamespace(fields={}),
        )
        for index, metrics in enumerate(
            [
                {
                    "gmvMinor": 100,
                    "orderCount": 1,
                    "itemsSold": 2,
                    "views": 200,
                    "productImpressions": 100,
                },
                {
                    "gmvMinor": 500,
                    "orderCount": 3,
                    "itemsSold": 4,
                    "views": 800,
                    "productImpressions": 300,
                },
            ]
        )
    ]

    assert video_summary_from_rows(rows) == {
        "videoCount": 2,
        "gmvMinor": 600,
        "orderCount": 4,
        "itemsSold": 6,
        "views": 1000,
        "productImpressions": 400,
    }
