from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services import hubstudio_raw_sample_capture as capture


@pytest.mark.asyncio
async def test_loaded_cross3_preparation_does_not_reload_existing_sample_page(monkeypatch):
    page = SimpleNamespace(
        url="https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=9622543325839925006",
        reload=AsyncMock(side_effect=AssertionError("Reload destroys the loaded review panel")),
        goto=AsyncMock(side_effect=AssertionError("Existing sample page must be reused")),
    )
    prepare = AsyncMock()
    reset = AsyncMock()
    first = AsyncMock()
    monkeypatch.setattr(capture, "prepare_reused_review", prepare, raising=False)
    # The safe preparation must precede request/response subscription.
    assert hasattr(capture, "prepare_reused_review")
    from backend.app.services import sample_review_page_refresh as refresh
    monkeypatch.setattr(refresh, "prepare_sample_review_page", prepare)
    monkeypatch.setattr(refresh, "reset_date_sort", reset)
    monkeypatch.setattr(refresh, "reset_first_review_page", first)
    assert await refresh.prepare_reused_review(page, "9622543325839925006", None)
    prepare.assert_awaited_once_with(page, select_free=True)
    reset.assert_awaited_once_with(page)
    first.assert_awaited_once_with(page)
    page.reload.assert_not_awaited()
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_shop_and_wrong_page_do_not_use_cross3_refresh():
    from backend.app.services import sample_review_page_refresh as refresh
    page = SimpleNamespace(url="https://example.test/elsewhere")
    assert not await refresh.prepare_reused_review(page, "9768147009521852682", None)
    assert not await refresh.prepare_reused_review(page, "9622543325839925006", "verified-url")


@pytest.mark.asyncio
async def test_late_preparation_response_cannot_enter_refreshed_raw_batch(monkeypatch):
    events = {}
    accepted = []
    completed = []

    class Store:
        def recover_completed(self):
            return None

        def abandon_capturing(self, reason):
            pass

        def start_batch(self):
            return 1

        def complete_batch(self, *args, **kwargs):
            completed.append(kwargs)
            return object()

    page = SimpleNamespace(on=lambda event, handler: events.update({event: handler}),
                           remove_listener=lambda event, handler: events.pop(event))
    request = lambda: SimpleNamespace(
        url="https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/group/list",
        method="POST", post_data='{"tab":10,"order_params":[],"search_params":[],"page":1}',
    )
    old, new = request(), request()

    async def refresh(_page):
        events["response"](SimpleNamespace(request=old, url=old.url, label="old"))
        events["request"](new)
        events["response"](SimpleNamespace(request=new, url=new.url, label="new"))

    async def read(response, page, platform, store, batch, sequence, marker, queue, observed):
        accepted.append(response.label)
        await queue.put(capture._CapturedPage(sequence, SimpleNamespace(next_page_token=None)))

    monkeypatch.setattr(capture, "prepare_reused_review", AsyncMock(return_value=True))
    monkeypatch.setattr(capture, "trigger_review_refresh", refresh)
    monkeypatch.setattr(capture, "_read_response", read)
    monkeypatch.setattr(capture, "validate_captured_pages", lambda pages: (0, 0))
    result = await capture.capture_review_batch_from_page(page, "9622543325839925006", Store())
    assert result.recovered is False
    assert accepted == ["new"]
    assert completed == [{"expected_total": 0, "captured_total": 0, "terminal_confirmed": True}]
    assert events == {}
