import asyncio
from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

from erp_api.services import affiliate_video_page_query
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_video_window_aggregation import split_video_query


def _query(start: date, end: date) -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=start,
        window_end=end,
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_video_page_aggregates_the_resolved_complete_chunk_plan(monkeypatch) -> None:
    query = _query(date(2026, 7, 8), date(2026, 9, 5))
    chunks = split_video_query(query)
    expected = {"items": [{"videoId": "video-1"}], "total": 1}
    resolve = AsyncMock(return_value=chunks)
    aggregate = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        affiliate_video_page_query,
        "resolve_complete_video_chunks",
        resolve,
        raising=False,
    )
    monkeypatch.setattr(
        affiliate_video_page_query,
        "aggregated_video_page",
        aggregate,
    )

    result = asyncio.run(
        affiliate_video_page_query.video_metric_page(
            object(),
            uuid4(),
            query,
            page=1,
            page_size=20,
            sort="affiliateGmvMinor",
            order="desc",
            creator_open_id=None,
        )
    )

    assert result == expected
    assert aggregate.await_args.args[3] == chunks
