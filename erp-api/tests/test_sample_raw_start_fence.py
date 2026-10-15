"""A reused final page or noninitial cursor must never become a full batch."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services import hubstudio_raw_sample_capture as capture
from backend.app.services import sample_raw_capture_metadata as metadata
from backend.app.services import sample_review_page_refresh as refresh
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_batch_validation import validate_stored_raw_pages


def _pages(numbers, *, cursor=None):
    return [SimpleNamespace(
        request_id=f"request-{index}", request_page=number,
        request_cursor=cursor if index == 0 and cursor is not None else json.dumps([["cur_page", number]]),
        response_has_more=index < len(numbers) - 1, response_total_count=0,
    ) for index, number in enumerate(numbers)]


def _validate(pages):
    return validate_stored_raw_pages(pages, expected_total=0, captured_total=0, terminal_confirmed=True)


@pytest.mark.parametrize("numbers", [[8], [8, 9], [0], [True], []])
def test_noninitial_or_missing_start_cannot_complete(numbers):
    with pytest.raises(RuntimeError, match="first page|page marker|no pages"):
        _validate(_pages(numbers))


@pytest.mark.parametrize("cursor", [
    '[["cur_page",1],["cursor","next-8"]]',
    '[["cur_page",1],["pagination.offset",50]]',
    '[["cur_page",1],["start",1]]',
    '[["cur_page",8]]',
    '[["cur_page",1],["cursor",true]]',
    "unverified-next-cursor",
    "page:1", "p1", "ui-page:1",
])
def test_first_page_with_noninitial_cursor_cannot_complete(cursor):
    with pytest.raises(RuntimeError, match="initial cursor"):
        _validate(_pages([1], cursor=cursor))


@pytest.mark.parametrize("cursor", [
    '[["cur_page",1]]',
    '[["pagination.page_num",1],["pagination.cursor",""]]',
    '[["page",1],["offset",0]]', "3:1",
])
def test_verified_initial_cursor_completes(cursor):
    assert _validate(_pages([1], cursor=cursor)) == 0


def test_complete_page_range_still_requires_every_page_and_terminal():
    assert _validate(_pages([1, 2, 3])) == 0
    with pytest.raises(RuntimeError, match="not contiguous"):
        _validate(_pages([1, 3]))
    with pytest.raises(RuntimeError, match="not contiguous|duplicate cursor"):
        _validate(_pages([1, 2, 2]))
    repeated = _pages([1, 2])
    repeated[1].request_id = repeated[0].request_id
    with pytest.raises(RuntimeError, match="duplicate request id"):
        _validate(repeated)
    repeated = _pages([1, 2])
    repeated[1].request_cursor = repeated[0].request_cursor
    with pytest.raises(RuntimeError, match="duplicate cursor"):
        _validate(repeated)
    incomplete = _pages([1, 2])
    incomplete[-1].response_has_more = True
    with pytest.raises(RuntimeError, match="terminal page"):
        _validate(incomplete)


@pytest.mark.parametrize("flag", [None, 0, 1, "false"])
def test_terminal_requires_explicit_boolean_has_more(flag):
    pages = _pages([1])
    pages[-1].response_has_more = flag
    with pytest.raises(RuntimeError, match="has_more.*invalid"):
        _validate(pages)


@pytest.mark.parametrize("body", [
    '{"tab":10,"order_params":[]}',
    '{"tab":10,"cur_page":true}',
    '{"tab":10,"cur_page":0}',
    '{"tab":10,"cur_page":1,"cursor":"next-8"}',
])
def test_request_marker_does_not_fabricate_a_valid_first_page(body):
    with pytest.raises((RuntimeError, ValueError), match="page marker|initial cursor"):
        metadata.parse_request_marker(body, fallback_page=1)


def test_live_cur_page_marker_is_preserved():
    marker = metadata.parse_request_marker('{"tab":10,"cur_page":8}', fallback_page=1)
    assert marker.page == 8


@pytest.mark.asyncio
async def test_cross3_reuse_returns_to_first_page_before_capture_subscription(monkeypatch):
    calls = []
    page = SimpleNamespace(url="https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=9622543325839925006")

    async def prepare(_page, **_kwargs):
        calls.append("prepare")

    async def reset(_page):
        calls.append("sort-reset")

    async def first(_page):
        calls.append("first-page")

    monkeypatch.setattr(refresh, "prepare_sample_review_page", prepare)
    monkeypatch.setattr(refresh, "reset_date_sort", reset)
    monkeypatch.setattr(refresh, "reset_first_review_page", first, raising=False)
    assert await refresh.prepare_reused_review(page, "9622543325839925006", None)
    assert calls == ["prepare", "sort-reset", "first-page"]


@pytest.mark.asyncio
async def test_first_page_reset_is_scoped_and_never_reload_or_new_page():
    class Locator:
        def __init__(self, count, selected="true"):
            self.total = count
            self.selected = selected
            self.click = AsyncMock()

        def filter(self, **_kwargs):
            return self

        async def count(self):
            return self.total

        async def get_attribute(self, _name):
            return self.selected

    reset = getattr(refresh, "reset_first_review_page", None)
    assert reset is not None
    first, active = Locator(1), Locator(1)
    page = SimpleNamespace(locator=lambda selector: active if "active" in selector else first,
                           reload=AsyncMock(), goto=AsyncMock())
    await reset(page)
    first.click.assert_not_awaited()
    page.reload.assert_not_awaited()
    page.goto.assert_not_awaited()
    first.total = 2
    with pytest.raises(RuntimeError, match="first_page_ambiguous"):
        await reset(page)
    first.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_page_response_is_queued_as_failure_before_any_raw_write(tmp_path, monkeypatch):
    events = {}
    store = SampleRawBatchStore(tmp_path, "shop")
    page = SimpleNamespace(on=lambda event, handler: events.update({event: handler}),
                           remove_listener=lambda event, handler: events.pop(event))

    async def load(*_args):
        response = SimpleNamespace(
            url="https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/group/list",
            request=SimpleNamespace(method="POST", post_data='{"tab":10,"order_params":[],"search_params":[],"cur_page":8}'),
        )
        events["response"](response)

    monkeypatch.setattr(capture, "prepare_reused_review", AsyncMock(return_value=False))
    monkeypatch.setattr(capture, "_load_first_page", load)
    with pytest.raises(RuntimeError, match="start at 1"):
        await asyncio.wait_for(capture.capture_review_batch_from_page(page, "shop", store), 1)
    assert store.recover_completed() is None
    assert list(tmp_path.rglob("page-*.json")) == []
    assert events == {}


@pytest.mark.asyncio
async def test_first_page_reset_clicks_only_exact_first_page(monkeypatch):
    class Locator:
        selected = "false"
        clicked = 0

        def filter(self, **kwargs):
            if "has_text" in kwargs:
                assert kwargs["has_text"].fullmatch("1")
                assert not kwargs["has_text"].fullmatch("10")
            return self

        async def count(self):
            return 1

        async def get_attribute(self, name):
            assert name == "aria-current"
            return self.selected

        async def click(self, **_kwargs):
            self.clicked += 1
            self.selected = "true"

    first, active = Locator(), Locator()
    page = SimpleNamespace(locator=lambda selector: active if "active" in selector else first)
    monkeypatch.setattr(refresh.asyncio, "sleep", AsyncMock())
    await refresh.reset_first_review_page(page)
    assert first.clicked == 1
    assert active.clicked == 0
