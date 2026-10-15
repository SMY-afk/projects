import asyncio

from backend.app.services.tiktok_affiliate_api_replay import (
    AffiliateApiReplay,
    replay_headers,
)


class FakeRequest:
    url = "https://affiliate.tiktokshopglobalselling.com/api/list?shop_id=1"

    def __init__(self) -> None:
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "cookie": "must-not-be-copied",
            "origin": "https://affiliate.tiktokshopglobalselling.com",
            "referer": "https://affiliate.tiktokshopglobalselling.com/page",
            "sec-fetch-site": "same-origin",
            "user-agent": "browser",
            "request-start-time": "stale-dynamic-value",
            "x-secsdk-csrf-token": "session-token",
        }


class FakePage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def evaluate(self, script: str, arg: dict[str, object]) -> int:
        self.calls.append((script, arg))
        return 200


def test_replay_headers_keep_api_headers_but_not_browser_credentials() -> None:
    headers = replay_headers(FakeRequest().headers)

    assert headers == {
        "accept": "application/json",
        "content-type": "application/json",
    }


def test_replay_posts_through_the_existing_page_session() -> None:
    async def run() -> tuple[int, FakePage]:
        page = FakePage()
        replay = AffiliateApiReplay(page)  # type: ignore[arg-type]
        await replay.capture(FakeRequest(), {"page": 1})  # type: ignore[arg-type]
        status = await replay.post({"page": 2})
        return status, page

    status, page = asyncio.run(run())

    assert status == 200
    assert len(page.calls) == 1
    assert "credentials: 'include'" in page.calls[0][0]
    assert "String(Date.now())" in page.calls[0][0]
    assert page.calls[0][1] == {
        "url": FakeRequest.url,
        "headers": {
            "accept": "application/json",
            "content-type": "application/json",
        },
        "body": {"page": 2},
    }


def test_replay_requires_a_captured_request_template() -> None:
    replay = AffiliateApiReplay(FakePage())  # type: ignore[arg-type]

    try:
        asyncio.run(replay.post({"page": 2}))
    except RuntimeError as error:
        assert str(error) == "affiliate_api_template_missing"
    else:
        raise AssertionError("Missing request template must reject direct replay")
