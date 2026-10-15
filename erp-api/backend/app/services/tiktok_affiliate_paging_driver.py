from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from playwright.async_api import Locator, Page

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    PAGINATION_STATE_SCRIPT,
    current_and_next,
)

PageRequester = Callable[[int], Awaitable[None]]
PageNumberProvider = Callable[[], int]


@dataclass(frozen=True)
class AffiliatePagingDriver:
    requester: PageRequester | None
    number_provider: PageNumberProvider | None

    def __post_init__(self) -> None:
        if (self.requester is None) != (self.number_provider is None):
            raise ValueError("Direct paging requires both pager callbacks.")

    @property
    def direct(self) -> bool:
        return self.requester is not None

    async def resolve(
        self,
        page: Page,
        selector: str,
    ) -> tuple[Locator | None, int | None, int | None]:
        if self.number_provider is not None:
            return None, self.number_provider(), None
        locator = page.locator(selector)
        items = await locator.evaluate_all(PAGINATION_STATE_SCRIPT)
        current_page, next_index = current_and_next(items)
        return locator, current_page, next_index

    async def advance(
        self,
        locator: Locator | None,
        next_index: int | None,
        next_page: int,
    ) -> None:
        if self.requester is not None:
            await self.requester(next_page)
            return
        assert locator is not None and next_index is not None
        await locator.nth(next_index).evaluate("(element) => element.click()")
