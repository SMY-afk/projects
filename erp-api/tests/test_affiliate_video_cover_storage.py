import asyncio
from uuid import uuid4

import httpx
import pytest

from erp_api.services.affiliate_video_cover_storage import (
    AffiliateVideoCoverStorage,
    AffiliateVideoCoverStorageError,
)


class FakeStorage:
    provider = "s3"
    bucket = "covers"

    def __init__(self) -> None:
        self.puts = []

    async def put(self, *args, **kwargs) -> None:
        self.puts.append((args, kwargs))


class HangingStorage(FakeStorage):
    async def put(self, *args, **kwargs) -> None:
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_video_cover_is_downloaded_and_stored() -> None:
    body = b"fresh-cover"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "image/webp"},
            request=request,
        )

    storage = FakeStorage()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = AffiliateVideoCoverStorage(storage, client=client)

    result = await service.store(
        "https://p16-common-sign.tiktokcdn-us.com/cover.webp?x-signature=fresh",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        video_id="video-1",
    )

    await client.aclose()
    assert result.object_key.endswith("/video-1.webp")
    assert storage.puts[0][0] == (result.object_key, body)
    assert storage.puts[0][1]["content_type"] == "image/webp"


@pytest.mark.asyncio
async def test_video_cover_rejects_untrusted_source_host() -> None:
    service = AffiliateVideoCoverStorage(FakeStorage())

    with pytest.raises(AffiliateVideoCoverStorageError, match="not allowed"):
        await service.store(
            "https://example.com/cover.jpg",
            tenant_id=uuid4(),
            shop_id=uuid4(),
            video_id="video-1",
        )


@pytest.mark.asyncio
async def test_video_cover_storage_timeout_does_not_block_capture() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"fresh-cover",
            headers={"content-type": "image/webp"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = AffiliateVideoCoverStorage(
        HangingStorage(),
        client=client,
        timeout_seconds=0.01,
    )

    with pytest.raises(AffiliateVideoCoverStorageError, match="storage failed"):
        await service.store(
            "https://p16-common-sign.tiktokcdn-us.com/cover.webp?fresh=1",
            tenant_id=uuid4(),
            shop_id=uuid4(),
            video_id="video-timeout",
        )

    await client.aclose()
