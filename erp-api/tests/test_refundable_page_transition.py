from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services import refundable_sample_capture as capture


@pytest.mark.asyncio
async def test_reused_paid_page_is_not_reloaded_and_resets_sticky_paid_tab(monkeypatch):
    url = "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request"
    page = SimpleNamespace(url=url, reload=AsyncMock(), goto=AsyncMock())
    select_free = AsyncMock()
    monkeypatch.setattr(capture, "select_free_sample_tab", select_free)

    await capture._prepare_paid_page(page, url)

    page.reload.assert_not_awaited()
    page.goto.assert_not_awaited()
    select_free.assert_awaited_once_with(page)
