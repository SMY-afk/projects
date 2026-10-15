import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from erp_api.services.affiliate_analytics_commit_service import (
    AffiliateAnalyticsCommitService,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliateSourcePageContext,
)
from erp_api.services.affiliate_center_source_adapters import (
    map_official_creator_page,
)
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
)


class FakeSyncRepository:
    def __init__(self, *, recorded: bool = False) -> None:
        self.events: list[tuple[str, object]] = []
        self.recorded = recorded

    async def has_recorded_page(self, *args, **kwargs) -> bool:
        return self.recorded

    async def record_page(self, tenant_id, run_id, **kwargs) -> None:
        self.events.append(("cursor", kwargs))

    async def complete_run(self, tenant_id, run_id, **kwargs):
        self.events.append(("complete", kwargs))
        return SimpleNamespace(status="succeeded")

    async def partial_run(self, tenant_id, run_id, **kwargs):
        self.events.append(("partial", kwargs))
        return SimpleNamespace(status="partial")


def _page() -> AffiliateCenterPageDTO:
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=UUID("e4408786-af60-545e-8f8c-5ef22a71e675"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )
    records = [
        {
            "username": f"@creator-{index}",
            "creatorOpenId": f"open-{index}",
            "currency": "USD",
        }
        for index in range(3)
    ]
    return map_official_creator_page(
        query,
        records,
        context=AffiliateSourcePageContext(
            request_id="request-1",
            pagination_mode="page_page_size",
            page_number=1,
            next_cursor="page:2",
            has_more=True,
        ),
        raw_payload={"data": {"stats": []}},
    )


def test_page_details_are_durable_before_recovery_cursor() -> None:
    repository = FakeSyncRepository()
    service = AffiliateAnalyticsCommitService(repository)

    async def run() -> None:
        async def persist_details(page: AffiliateCenterPageDTO) -> int:
            assert len(page.records) == 3
            repository.events.append(("details", 3))
            return 3

        await service.commit_page(uuid4(), uuid4(), _page(), persist_details)

    asyncio.run(run())

    assert [event[0] for event in repository.events] == ["details", "cursor"]
    assert repository.events[1][1]["persisted_count"] == 3
    assert repository.events[1][1]["page_number"] == 1


def test_committed_page_replay_skips_details_raw_payload_and_cursor() -> None:
    repository = FakeSyncRepository(recorded=True)
    service = AffiliateAnalyticsCommitService(repository)

    async def persist_details(page: AffiliateCenterPageDTO) -> int:
        raise AssertionError("committed page details must not be written again")

    persisted = asyncio.run(
        service.commit_page(uuid4(), uuid4(), _page(), persist_details)
    )

    assert persisted == 0
    assert repository.events == []


def test_failed_detail_write_never_advances_recovery_cursor() -> None:
    repository = FakeSyncRepository()
    service = AffiliateAnalyticsCommitService(repository)

    async def persist_details(page: AffiliateCenterPageDTO) -> int:
        raise RuntimeError("detail write failed")

    with pytest.raises(RuntimeError, match="detail write failed"):
        asyncio.run(service.commit_page(uuid4(), uuid4(), _page(), persist_details))

    assert repository.events == []


def test_creator_completion_promotes_repository_recovery_cursor() -> None:
    repository = FakeSyncRepository()
    service = AffiliateAnalyticsCommitService(repository)

    result = asyncio.run(
        service.complete_creator_report(
            uuid4(),
            uuid4(),
            uuid4(),
            AffiliateCreatorReportCompletion(
                expected_total=1,
                pages_fetched=1,
                records_received=1,
                records_unique=1,
                duplicate_count=0,
                completeness_reason="complete",
            ),
        )
    )

    assert result.status == "succeeded"
    assert len(repository.events) == 1
    event, kwargs = repository.events[0]
    assert event == "complete"
    assert kwargs["committed_cursor"] is None
    assert kwargs["creator_report_id"] is not None
    assert kwargs["report_completion"].records_unique == 1


@pytest.mark.parametrize(
    "reason",
    ["total_count_mismatch", "cursor_interrupted", "page_failed"],
)
def test_video_partial_outcomes_never_call_complete(reason: str) -> None:
    repository = FakeSyncRepository()
    service = AffiliateAnalyticsCommitService(repository)

    result = asyncio.run(
        service.mark_video_partial(
            uuid4(),
            uuid4(),
            reason,  # type: ignore[arg-type]
        )
    )

    assert result.status == "partial"
    assert repository.events == [("partial", {"reason": reason})]
