from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_creator_window_read import aggregated_creator_page


def report(start, end):
    return AffiliateCreatorReport(
        id=uuid4(),
        period_start=date(2026, 10, start),
        period_end=date(2026, 10, end),
        captured_at=datetime(2026, 10, 12, tzinfo=UTC),
        status="complete",
        currency="USD",
        shop_timezone="America/Los_Angeles",
        records_unique=0,
        revision_no=1,
    )


async def read(reports):
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=uuid4(),
        window_start=date(2026, 10, 4),
        window_end=date(2026, 10, 10),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalars=lambda: reports),
                SimpleNamespace(all=list),
            ]
        )
    )
    page = await aggregated_creator_page(
        session,
        uuid4(),
        query,
        page=1,
        page_size=50,
        sort="affiliateGmvMinor",
        order="desc",
    )
    return page, session


@pytest.mark.asyncio
async def test_mixed_complete_windows_cover_real_shop_week_without_double_counting():
    reports = [
        report(4, 5),
        report(4, 4),
        report(5, 6),
        report(7, 8),
        report(7, 7),
        report(8, 9),
        report(9, 10),
    ]
    page, session = await read(reports)
    assert page is not None
    assert page["report"]["windowStart"] == date(2026, 10, 4)
    assert page["report"]["windowEnd"] == date(2026, 10, 10)
    assert page["report"]["sourceMetadata"]["componentReportCount"] == 4
    parameters = session.execute.call_args_list[1].args[0].compile().params
    selected_ids = next(
        value for value in parameters.values() if isinstance(value, list)
    )
    assert selected_ids == [reports[index].id for index in [1, 2, 3, 6]]


@pytest.mark.asyncio
async def test_gap_does_not_return_a_complete_report():
    page, session = await read([report(4, 4), report(5, 6), report(7, 8), report(9, 9)])
    assert page is None
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_overlapping_reports_cannot_be_added_to_fake_complete_coverage():
    page, session = await read(
        [report(4, 5), report(5, 6), report(7, 8), report(9, 10)]
    )
    assert page is None
    assert session.execute.await_count == 1
