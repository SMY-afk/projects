import asyncio

import pytest

from backend.app.services.tiktok_affiliate_capture_dispatcher import (
    TikTokAffiliateCaptureDispatcher,
)


class FakeSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.pages = []
        self.terminals = []

    async def persist_page(self, *args) -> None:
        self.pages.append(args)

    async def finalize_resource(self, *args) -> None:
        self.terminals.append(args)


def test_dispatcher_keeps_creator_and_video_sessions_independent() -> None:
    creator, video = FakeSession("creator"), FakeSession("video")
    dispatcher = TikTokAffiliateCaptureDispatcher(creator, video)

    asyncio.run(dispatcher.persist_page("creators", {}, {}, None, 1, 2))
    asyncio.run(dispatcher.persist_page("videos", {}, {}, None, 1, None))
    asyncio.run(dispatcher.finalize_resource("creators", {"status": "complete"}))
    asyncio.run(
        dispatcher.finalize_resource(
            "videos",
            {"status": "partial", "failure_category": "page_failed"},
        )
    )

    assert creator.pages[0][0] == "creators"
    assert video.pages[0][0] == "videos"
    assert creator.terminals == [("creators", {"status": "complete"})]
    assert video.terminals == [
        ("videos", {"status": "partial", "failure_category": "page_failed"})
    ]


def test_dispatcher_rejects_unknown_resources() -> None:
    dispatcher = TikTokAffiliateCaptureDispatcher(
        FakeSession("creator"), FakeSession("video")
    )

    with pytest.raises(ValueError, match="Unknown affiliate capture resource"):
        asyncio.run(dispatcher.finalize_resource("other", {}))
