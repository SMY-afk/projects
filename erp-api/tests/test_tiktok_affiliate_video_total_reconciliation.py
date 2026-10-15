import asyncio
from datetime import date
from uuid import UUID

import pytest

from backend.app.services import tiktok_affiliate_video_total_reconciliation
from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_video_total_reconciliation import (
    verify_video_total_drift,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)


class FakePage:
    def __init__(self, identifiers: list[str], counts: list[int] | None = None) -> None:
        self.identifiers = identifiers
        self.counts = counts if counts is not None else [1, 1]
        self.payload = None

    async def evaluate(self, _script, payload):
        self.payload = payload
        return {
            "accepted": True,
            "ids": self.identifiers,
            "counts": self.counts,
        }


def _context(page_no: int = 2) -> AffiliateAnalyticsResponseContext:
    return AffiliateAnalyticsResponseContext(
        "platform-shop-1",
        "request-1",
        request_url=(
            "https://affiliate-us.tiktok.com"
            "/api/v1/oec/affiliate/compass/transaction/detail_list/get"
        ),
        request_headers={"content-type": "application/json"},
        request_body={
            "params": {
                "video_list_params_v2": [
                    {
                        "page_param": {"page_no": page_no, "page_size": 2},
                        "sorter": {"sort_type": 1, "order_type": 1},
                    }
                ]
            }
        },
    )


def _snapshot() -> dict[str, object]:
    return {
        "status": "partial",
        "failure_category": "total_count_mismatch",
        "expected_total": 3,
        "records_unique": 2,
        "duplicates": 0,
        "pages_fetched": 2,
        "records_received": 2,
        "first_page_index": 1,
        "last_page_index": 2,
    }


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=UUID(int=1),
        window_start=date(2026, 7, 10),
        window_end=date(2026, 7, 10),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_reverse_sort_and_export_must_return_the_same_identifier_set(
    monkeypatch,
) -> None:
    page = FakePage(["video-1", "video-2"])

    async def download_export(_page, _query):
        return b"xlsx", "task-id", object(), None

    async def delete_export(_download):
        return None

    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "download_video_export",
        download_export,
    )
    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "delete_download",
        delete_export,
    )
    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "read_first_worksheet",
        lambda _content: iter(
            [
                ["Video title", "Video ID", "GMV"],
                ["First", "video-1", "1.00"],
                ["Second", "video-2", "2.00"],
                [None, None, "3.00"],
            ]
        ),
    )

    verified = asyncio.run(
        verify_video_total_drift(
            page,  # type: ignore[arg-type]
            _query(),
            _snapshot(),
            _context(),
            frozenset({"video-1", "video-2"}),
        )
    )

    assert verified is True
    assert page.payload["pages"] == 2
    assert (
        page.payload["body"]["params"]["video_list_params_v2"][0]["sorter"][
            "order_type"
        ]
        == 2
    )


def test_reverse_sort_rejects_a_different_identifier_set() -> None:
    verified = asyncio.run(
        verify_video_total_drift(
            FakePage(["video-1", "video-3"]),  # type: ignore[arg-type]
            _query(),
            _snapshot(),
            _context(),
            frozenset({"video-1", "video-2"}),
        )
    )

    assert verified is False


def test_reverse_verification_logs_browser_cancellation(monkeypatch) -> None:
    events = []

    class CancelledPage:
        async def evaluate(self, _script, _payload):
            raise asyncio.CancelledError

    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "capture_log",
        lambda event, **fields: events.append((event, fields)),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            verify_video_total_drift(
                CancelledPage(),  # type: ignore[arg-type]
                _query(),
                _snapshot(),
                _context(),
                frozenset({"video-1", "video-2"}),
            )
        )
    assert events == [
        ("affiliate_video_drift_rejected", {"reason": "reverse_cancelled"})
    ]


def test_three_record_drift_requires_complete_reverse_pages_and_export(
    monkeypatch,
) -> None:
    page = FakePage(["a", "b", "c", "d"], [1, 1, 1, 1])
    snapshot = _snapshot() | {
        "expected_total": 7,
        "records_unique": 4,
        "records_received": 4,
        "pages_fetched": 4,
        "last_page_index": 4,
    }

    async def download_export(_page, _query):
        return b"xlsx", "task", object(), None

    async def delete_export(_download):
        return None

    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "download_video_export",
        download_export,
    )
    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "delete_download",
        delete_export,
    )
    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "read_first_worksheet",
        lambda _content: iter([["Video ID"], *[[id_] for id_ in ["a", "b", "c", "d"]]]),
    )
    assert (
        asyncio.run(
            verify_video_total_drift(
                page,
                _query(),
                snapshot,
                _context(4),
                frozenset({"a", "b", "c", "d"}),
            )
        )
        is True
    )
    assert page.payload["pages"] == 4
    page.counts = [1, 1, 2]
    assert (
        asyncio.run(
            verify_video_total_drift(
                page,
                _query(),
                snapshot,
                _context(4),
                frozenset({"a", "b", "c", "d"}),
            )
        )
        is False
    )


def test_export_missing_an_id_cannot_confirm_total_drift(monkeypatch) -> None:
    page = FakePage(["video-1", "video-2"])

    async def download_export(_page, _query):
        return b"xlsx", "task", object(), None

    async def delete_export(_download):
        return None

    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "download_video_export",
        download_export,
    )
    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "delete_download",
        delete_export,
    )
    monkeypatch.setattr(
        tiktok_affiliate_video_total_reconciliation,
        "read_first_worksheet",
        lambda _content: iter([["Video ID"], ["video-1"]]),
    )
    assert (
        asyncio.run(
            verify_video_total_drift(
                page,
                _query(),
                _snapshot(),
                _context(),
                frozenset({"video-1", "video-2"}),
            )
        )
        is False
    )


def test_drift_larger_than_three_cannot_be_reconciled() -> None:
    page = FakePage(["video-1", "video-2"])
    snapshot = _snapshot() | {"expected_total": 7}
    assert (
        asyncio.run(
            verify_video_total_drift(
                page,
                _query(),
                snapshot,
                _context(),
                frozenset({"video-1", "video-2"}),
            )
        )
        is False
    )
    assert page.payload is None
