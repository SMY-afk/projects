from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services import tiktok_affiliate_intent_page
from backend.app.services.tiktok_affiliate_intent_page import prepare_intent_page
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntent,
)


def _intent() -> AffiliateCaptureIntent:
    return AffiliateCaptureIntent(
        run_id=uuid4(),
        job_id="affiliate-intent:test",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        resource="creators",
        resource_type="affiliate_creator",
        platform_shop_id="platform-shop-1",
        shop_timezone="America/Los_Angeles",
        currency="USD",
        window_start=datetime(2026, 8, 1, 7, tzinfo=UTC),
        window_end=datetime(2026, 8, 8, 7, tzinfo=UTC),
    )


def test_prepare_intent_uses_only_one_clean_matching_creator_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = (
        "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
        "?shop_id=platform-shop-1"
    )
    blocked = SimpleNamespace(url=url)
    clean = SimpleNamespace(url=url)
    prepared_pages = []

    async def security(page):
        return ("session_required", "captcha") if page is blocked else None

    async def prepare_trigger(page, query):
        prepared_pages.append(page)

        async def trigger() -> None:
            return None

        return trigger

    monkeypatch.setattr(tiktok_affiliate_intent_page, "page_security_failure", security)
    monkeypatch.setattr(
        tiktok_affiliate_intent_page, "_prepare_trigger", prepare_trigger
    )

    prepared = asyncio.run(
        prepare_intent_page(
            [SimpleNamespace(pages=[blocked, clean])],
            _intent(),
        )
    )

    assert prepared.page is clean
    assert prepared_pages == [clean]
