import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_creator_capture import (
    TikTokAffiliateCreatorCaptureSession,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterResource


class FakeReadRepository:
    def __init__(self, shop_id) -> None:
        self.shop_id = shop_id
        self.calls = []

    async def get_shop_context_by_platform_id(self, tenant_id, platform_shop_id):
        self.calls.append((tenant_id, platform_shop_id))
        return {
            "shopId": self.shop_id,
            "shopTimezone": "America/Los_Angeles",
            "currency": "USD",
        }


class FakeSyncRepository:
    def __init__(self, events) -> None:
        self.events = events

    async def has_recorded_page(self, *args, **kwargs):
        return False

    async def record_page(self, tenant_id, run_id, **kwargs):
        self.events.append(("cursor", tenant_id, run_id, kwargs))

    async def complete_run(self, tenant_id, run_id, **kwargs):
        self.events.append(("complete", tenant_id, run_id, kwargs))
        return SimpleNamespace(status="succeeded")

    async def partial_run(self, tenant_id, run_id, **kwargs):
        self.events.append(("partial", tenant_id, run_id, kwargs))
        return SimpleNamespace(status="partial")


class FakePersistence:
    def __init__(self, events) -> None:
        self.events = events
        self.run_id, self.report_id = uuid4(), uuid4()

    async def begin_capture(self, tenant_id, query, **kwargs):
        self.events.append(("begin", tenant_id, query, kwargs))
        return self.run_id, self.report_id

    async def persist_page(self, tenant_id, report_id, page):
        self.events.append(("details", tenant_id, report_id, page))
        return len(page.records)


def _payload(**filter_overrides) -> dict[str, object]:
    creator_filter = {
        "shop_id": "platform-shop-1",
        "collaboration_type": "target",
        "creator_tier": [1, 2],
        "unapproved": "ignored",
        "signature": "must-not-be-copied",
        **filter_overrides,
    }
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "segments": [
                {
                    "filter": creator_filter,
                    "list_control": {
                        "next_pagination": {
                            "has_more": False,
                            "next_page": 2,
                            "total": 1,
                            "total_page": 1,
                        },
                        "rules": [],
                    },
                    "time_descriptor": {
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                        "timezone_offset": -7,
                    },
                    "timed_lists": [
                        {
                            "start": "2026-08-01",
                            "end": "2026-08-07",
                            "stats": [
                                {
                                    "id": "creator-1",
                                    "handle": "@creator",
                                    "revenue": {
                                        "amount": "12.34",
                                        "currency_code": "USD",
                                    },
                                    "order_cnt": 2,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _build():
    tenant_id, shop_id = uuid4(), uuid4()
    repository = FakeReadRepository(shop_id)
    session = TikTokAffiliateCreatorCaptureSession(
        tenant_id,
        repository,  # type: ignore[arg-type]
        approved_filter_fields={"collaboration_type", "creator_tier"},
    )
    return session, repository, tenant_id, shop_id


def _build_persistent():
    tenant_id, shop_id = uuid4(), uuid4()
    events = []
    persistence = FakePersistence(events)
    session = TikTokAffiliateCreatorCaptureSession(
        tenant_id,
        FakeReadRepository(shop_id),  # type: ignore[arg-type]
        FakeSyncRepository(events),  # type: ignore[arg-type]
        persistence,  # type: ignore[arg-type]
        approved_filter_fields={"collaboration_type", "creator_tier"},
    )
    return session, persistence, events, tenant_id


def test_creator_session_extracts_frozen_query_dimensions_from_payload() -> None:
    session, repository, tenant_id, shop_id = _build()

    context = asyncio.run(
        session.resolve_capture_context(
            _payload(),
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
        )
    )

    assert repository.calls == [(tenant_id, "platform-shop-1")]
    assert context.platform_shop_id == "platform-shop-1"
    assert context.timezone_offset_hours == "-7"
    assert context.query.resource is AffiliateCenterResource.CREATORS
    assert context.query.shop_id == shop_id
    assert context.query.window_start.isoformat() == "2026-08-01"
    assert context.query.window_end.isoformat() == "2026-08-07"
    assert context.query.shop_timezone == "America/Los_Angeles"
    assert context.query.currency == "USD"
    assert context.query.filters == {
        "collaboration_type": "target",
        "creator_tier": [1, 2],
    }


def test_creator_session_builds_the_shared_page_dto() -> None:
    session, *_ = _build()

    page = asyncio.run(
        session.build_page(
            _payload(),
            {"pagination": {"mode": "page_page_size"}},
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
            page_number=1,
            next_page_number=None,
        )
    )

    assert page.resource is AffiliateCenterResource.CREATORS
    assert page.request_id == "request-1"
    assert page.pagination.mode == "page_page_size"
    assert page.pagination.has_more is False
    assert page.pagination.total_count == 1
    assert page.records[0].username == "@creator"
    assert page.records[0].affiliate_gmv_minor == 1234


def test_creator_session_rejects_payload_and_response_shop_mismatch() -> None:
    session, *_ = _build()

    with pytest.raises(ValueError, match="shop identifier mismatch"):
        asyncio.run(
            session.resolve_capture_context(
                _payload(),
                AffiliateAnalyticsResponseContext("other-shop", "request-1"),
            )
        )


def test_creator_session_rejects_timezone_offset_mismatch() -> None:
    session, *_ = _build()
    payload = _payload()
    payload["data"]["segments"][0]["time_descriptor"]["timezone_offset"] = 8

    with pytest.raises(ValueError, match="timezone offset"):
        asyncio.run(
            session.resolve_capture_context(
                payload,
                AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
            )
        )


def test_creator_session_falls_back_to_shop_currency_for_empty_page() -> None:
    session, *_ = _build()
    payload = _payload()
    payload["data"]["segments"][0]["timed_lists"][0]["stats"] = []

    context = asyncio.run(
        session.resolve_capture_context(
            payload,
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
        )
    )

    assert context.query.currency == "USD"


def test_creator_session_writes_details_before_recovery_cursor() -> None:
    session, persistence, events, tenant_id = _build_persistent()
    context = AffiliateAnalyticsResponseContext("platform-shop-1", "request-1")

    asyncio.run(
        session.persist_page(
            "creators",
            _payload(),
            {"pagination": {"mode": "page_page_size"}},
            context,
            1,
            None,
        )
    )

    assert [event[0] for event in events] == ["begin", "details", "cursor"]
    assert events[0][1] == tenant_id
    assert events[0][3]["platform_shop_id"] == "platform-shop-1"
    assert events[1][2] == persistence.report_id
    assert events[2][2] == persistence.run_id
    assert events[2][3]["persisted_count"] == 1
    assert events[2][3]["platform_request_id"] == "request-1"


def test_creator_export_starts_a_browser_export_report() -> None:
    session, _, events, _ = _build_persistent()
    page = asyncio.run(
        session.build_page(
            _payload(),
            {"pagination": {"mode": "page_page_size"}},
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
            1,
            None,
        )
    )

    asyncio.run(
        session.persist_mapped_page(
            replace(page, source_kind="browser_export"),
            platform_shop_id="platform-shop-1",
        )
    )

    assert events[0][3]["source_kind"] == "browser_export"


def test_creator_session_completes_or_partials_report_once() -> None:
    complete, persistence, events, _ = _build_persistent()
    context = AffiliateAnalyticsResponseContext("platform-shop-1", "request-1")
    asyncio.run(complete.persist_page("creators", _payload(), {}, context, 1, None))
    snapshot = {
        "status": "complete",
        "expected_total": 1,
        "pages_fetched": 1,
        "records_received": 1,
        "records_unique": 1,
        "duplicates": 0,
        "last_page_index": 1,
    }
    asyncio.run(complete.finalize_resource("creators", snapshot))
    asyncio.run(complete.finalize_resource("creators", snapshot))

    final = events[-1]
    assert [event[0] for event in events].count("complete") == 1
    assert final[2] == persistence.run_id
    assert final[3]["creator_report_id"] == persistence.report_id
    assert final[3]["committed_cursor"] is None
    assert final[3]["report_completion"].records_unique == 1

    partial, persistence, events, _ = _build_persistent()
    asyncio.run(partial.persist_page("creators", _payload(), {}, context, 1, None))
    asyncio.run(
        partial.finalize_resource(
            "creators",
            {
                **snapshot,
                "status": "partial",
                "failure_category": "max_pages_exceeded",
            },
        )
    )
    assert events[-1][0] == "partial"
    assert events[-1][2] == persistence.run_id
    assert events[-1][3]["report_partial"].completeness_reason == "page_failed"
