"""A reused review page must not depend on hidden or replacement sort values."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services import sample_request_page_controls as controls
from backend.app.services import sample_review_page_refresh as refresh


class SortValues:
    def __init__(self, *items):
        self.items = items

    def filter(self, *, visible):
        assert visible is True
        return SortValues(*(item for item in self.items if item.visible))

    async def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


def value(text, *, visible=True):
    return SimpleNamespace(visible=visible, inner_text=AsyncMock(return_value=text))


@pytest.mark.asyncio
async def test_hidden_old_sort_cannot_override_visible_request_date():
    hidden, current = value("Relevancy", visible=False), value("申请日期")
    page = SimpleNamespace(locator=lambda _selector: SortValues(hidden, current))
    state, locator = await controls._sort_state(page)
    assert state == "date"
    assert locator is current
    hidden.inner_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_visible_sort_controls_wait_instead_of_picking_first():
    page = SimpleNamespace(
        locator=lambda _selector: SortValues(value("Relevancy"), value("Request date"))
    )
    assert await controls._sort_state(page) == (None, None)


@pytest.mark.asyncio
async def test_loaded_cross7_preparation_does_not_reload_existing_review(monkeypatch):
    page = SimpleNamespace(
        url=("https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
             "sample-request?shop_id=9121478993551097445"),
        reload=AsyncMock(side_effect=AssertionError("Do not reload the approved page")),
        goto=AsyncMock(side_effect=AssertionError("Do not navigate the approved page")),
    )
    prepare, reset, first = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(refresh, "prepare_sample_review_page", prepare)
    monkeypatch.setattr(refresh, "reset_date_sort", reset)
    monkeypatch.setattr(refresh, "reset_first_review_page", first)
    assert await refresh.prepare_reused_review(page, "9121478993551097445", None)
    prepare.assert_awaited_once_with(page, select_free=True)
    reset.assert_awaited_once_with(page)
    first.assert_awaited_once_with(page)
    page.reload.assert_not_awaited()
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross7_reuse_requires_existing_expected_shop_page():
    page = SimpleNamespace(url="https://example.test/not-a-sample-page")
    assert not await refresh.prepare_reused_review(page, "9121478993551097445", None)
    page.url = ("https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
                "sample-request?shop_id=9121478993551097445")
    assert not await refresh.prepare_reused_review(page, "9121478993551097445", "initial-url")


@pytest.mark.asyncio
async def test_cross7_final_page_resets_before_capture_subscription(monkeypatch):
    calls = []

    class Pager:
        selected = False

        def filter(self, **kwargs):
            if "has_text" in kwargs:
                assert kwargs["has_text"].fullmatch("1")
                assert not kwargs["has_text"].fullmatch("2")
            return self

        async def count(self):
            return 1

        async def get_attribute(self, name):
            assert name == "aria-current"
            return "true" if self.selected else "false"

        async def click(self, **_kwargs):
            calls.append("first-page")
            self.selected = True

    first, active = Pager(), Pager()
    page = SimpleNamespace(
        url=("https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
             "sample-request?shop_id=9121478993551097445"),
        locator=lambda selector: active if "active" in selector else first,
        reload=AsyncMock(), goto=AsyncMock(),
    )

    async def prepare(_page, **kwargs):
        assert kwargs == {"select_free": True}
        calls.append("free-review-date")

    async def reset(_page):
        calls.append("relevance-reset")

    monkeypatch.setattr(refresh, "prepare_sample_review_page", prepare)
    monkeypatch.setattr(refresh, "reset_date_sort", reset)
    assert await refresh.prepare_reused_review(page, "9121478993551097445", None)
    assert calls == ["free-review-date", "relevance-reset", "first-page"]
    assert first.selected
    assert not active.selected
    page.reload.assert_not_awaited()
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_temporary_visible_sort_replacement_settles_without_more_wait(monkeypatch):
    current = value("申请日期")
    snapshots = iter([
        SortValues(value("Relevancy"), current),
        SortValues(current),
    ])
    page = SimpleNamespace(locator=lambda _selector: next(snapshots))
    sleep = AsyncMock()
    monkeypatch.setattr(controls.asyncio, "sleep", sleep)
    assert await controls._wait_for_sort(page, attempts=2, expected="date") == ("date", current)
    sleep.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_persistent_visible_sort_ambiguity_stays_blocked():
    page = SimpleNamespace(
        locator=lambda _selector: SortValues(value("申请日期"), value("Request date"))
    )
    with pytest.raises(RuntimeError, match="sample_request_date_sort_unavailable"):
        await controls._wait_for_sort(page, attempts=1, expected="date")
