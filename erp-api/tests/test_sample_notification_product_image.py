import httpx
import pytest

import erp_api.services.sample_notification_product_image as product_image_module
from erp_api.services.sample_notification_product_image import (
    SampleNotificationProductImageError,
    SampleNotificationProductImageService,
)


class FakeFeishuClient:
    def __init__(self) -> None:
        self.uploads = []

    async def upload_message_image(self, **kwargs):
        self.uploads.append(kwargs)
        return "img_v2_product"


@pytest.mark.asyncio
async def test_product_image_is_downloaded_from_tiktok_cdn_and_uploaded() -> None:
    body = b"real-product-image"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "p16-oec-general-useast5.ttcdn-us.com"
        return httpx.Response(
            200,
            headers={"content-type": "image/webp"},
            content=body,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feishu = FakeFeishuClient()
    service = SampleNotificationProductImageService(feishu, client=client)

    image_key = await service.resolve_img_key(
        "https://p16-oec-general-useast5.ttcdn-us.com/product.webp?token=private"
    )

    assert image_key == "img_v2_product"
    assert feishu.uploads == [{"image": body, "content_type": "image/webp"}]
    await client.aclose()


@pytest.mark.asyncio
async def test_product_image_download_does_not_inherit_system_proxy(
    monkeypatch,
) -> None:
    captured_options = {}
    real_async_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"product-image",
        )

    def build_client(**kwargs):
        captured_options.update(kwargs)
        return real_async_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(product_image_module.httpx, "AsyncClient", build_client)
    service = SampleNotificationProductImageService(FakeFeishuClient())

    await service.resolve_img_key(
        "https://p16-oec-general-useast5.ttcdn-us.com/product.jpg"
    )

    assert captured_options["trust_env"] is False


@pytest.mark.asyncio
async def test_product_image_rejects_non_tiktok_host_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"image")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SampleNotificationProductImageService(FakeFeishuClient(), client=client)

    with pytest.raises(SampleNotificationProductImageError, match="not allowed"):
        await service.resolve_img_key("https://evil.example/product.jpg")

    assert calls == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_product_image_availability_rejects_broken_and_non_image_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/missing.webp":
            return httpx.Response(404)
        if request.url.path == "/corrupt.webp":
            return httpx.Response(
                200, headers={"content-type": "image/webp"}, content=b"not an image"
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"no")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feishu = FakeFeishuClient()
    service = SampleNotificationProductImageService(feishu, client=client)

    assert not await service.is_available(
        "https://p16-oec-general-useast5.ttcdn-us.com/missing.webp"
    )
    assert not await service.is_available(
        "https://p16-oec-general-useast5.ttcdn-us.com/broken.webp"
    )
    assert not await service.is_available(
        "https://p16-oec-general-useast5.ttcdn-us.com/corrupt.webp"
    )
    assert not await service.is_available("https://evil.example/image.webp")
    assert feishu.uploads == []
    await client.aclose()


@pytest.mark.asyncio
async def test_product_image_availability_accepts_reachable_webp():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/webp"},
            content=b"RIFF1234WEBPimage-data",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SampleNotificationProductImageService(FakeFeishuClient(), client=client)

    assert await service.is_available(
        "https://p16-oec-general-useast5.ttcdn-us.com/product.webp"
    )
    await client.aclose()
