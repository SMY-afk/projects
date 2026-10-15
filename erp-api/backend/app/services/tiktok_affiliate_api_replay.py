from __future__ import annotations

import copy
from collections.abc import Mapping

from playwright.async_api import Page, Request

_REPLAY_HEADER_ALLOWLIST = {"accept", "content-type"}
_REPLAY_SCRIPT = """async ({url, headers, body}) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    const requestHeaders = {
        ...headers,
        'request-start-time': String(Date.now()),
    };
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: requestHeaders,
            credentials: 'include',
            body: JSON.stringify(body),
            signal: controller.signal,
        });
        await response.arrayBuffer();
        return response.status;
    } finally {
        clearTimeout(timeout);
    }
}"""


def replay_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Keep request semantics in memory while the browser supplies credentials."""
    return {
        name.casefold(): value
        for name, value in headers.items()
        if name.casefold() in _REPLAY_HEADER_ALLOWLIST
    }


class AffiliateApiReplay:
    """Replay a captured data request inside its existing signed-in page."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._url: str | None = None
        self._headers: dict[str, str] = {}
        self.template_body: dict[str, object] | None = None

    async def capture(self, request: Request, body: dict[str, object]) -> None:
        if self.template_body is not None:
            return
        self._url = request.url
        self._headers = replay_headers(request.headers)
        self.template_body = copy.deepcopy(body)

    async def post(self, body: dict[str, object]) -> int:
        if self._url is None or self.template_body is None:
            raise RuntimeError("affiliate_api_template_missing")
        status = await self._page.evaluate(
            _REPLAY_SCRIPT,
            {
                "url": self._url,
                "headers": self._headers,
                "body": body,
            },
        )
        if isinstance(status, bool) or not isinstance(status, int):
            raise TypeError("affiliate_api_status_invalid")
        return status
