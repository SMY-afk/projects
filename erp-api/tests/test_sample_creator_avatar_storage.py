import hashlib
from uuid import uuid4

import httpx
import pytest

from erp_api.services.sample_creator_avatar_storage import (
    SampleCreatorAvatarError,
    SampleCreatorAvatarStorage,
    extract_creator_avatar_source,
)


class FakeStorage:
    def __init__(self) -> None:
        self.puts = []

    async def put(self, *args, **kwargs) -> None:
        self.puts.append((args, kwargs))


@pytest.mark.asyncio
async def test_avatar_is_downloaded_from_allowlist_and_stored_by_content_hash() -> None:
    body = b"safe-image-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "p16-common-sign.tiktokcdn-us.com"
        assert "refresh_token" in request.url.params
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=body,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    service = SampleCreatorAvatarStorage(storage, client=client)

    result = await service.store(
        "https://p16-common-sign.tiktokcdn-us.com/a.jpg?refresh_token=private",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        creator_open_id="creator-1",
    )

    digest = hashlib.sha256(body).hexdigest()
    assert result.source_hash == digest
    assert result.object_key.endswith(f"/{digest}.jpg")
    assert storage.puts[0][0] == (result.object_key, body)
    assert storage.puts[0][1]["metadata"] == {"sha256": digest}
    assert "refresh_token" not in repr(storage.puts)
    await client.aclose()


@pytest.mark.asyncio
async def test_avatar_rejects_non_tiktok_host_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"image")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SampleCreatorAvatarStorage(FakeStorage(), client=client)

    with pytest.raises(SampleCreatorAvatarError, match="not allowed"):
        await service.store(
            "https://evil.example/a.jpg?token=private",
            tenant_id=uuid4(),
            shop_id=uuid4(),
            creator_open_id="creator-1",
        )

    assert calls == 0
    await client.aclose()


def test_avatar_source_supports_sample_and_performance_shapes() -> None:
    assert (
        extract_creator_avatar_source(
            {
                "creator": {
                    "avatar_url": "https://cdn.test/sample.jpg",
                    "performance": {
                        "avatar": {"url": "https://cdn.test/performance.jpg"}
                    },
                }
            }
        )
        == "https://cdn.test/performance.jpg"
    )
