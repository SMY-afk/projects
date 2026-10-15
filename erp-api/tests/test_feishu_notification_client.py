import json

import httpx
import pytest

from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_client import FeishuSampleClient


def _clients(handler):
    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource",
        transport=httpx.MockTransport(handler),
    )
    token_provider = FeishuSampleClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=http_client,
    )
    return FeishuNotificationClient(
        token_provider,
        client=http_client,
        retry_delays=(),
    )


@pytest.mark.asyncio
async def test_send_text_uses_open_id_and_stable_uuid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.url.path == "/open-apis/im/v1/messages"
        assert request.url.params["receive_id_type"] == "open_id"
        assert request.headers["Authorization"] == "Bearer tenant-token"
        body = json.loads(request.content)
        assert body["receive_id"] == "ou-bd"
        assert body["msg_type"] == "text"
        assert body["uuid"] == "76666bd5-8a9b-5e5e-a404-d82d886ad259"
        assert json.loads(body["content"])["text"] == "New sample"
        return httpx.Response(
            200,
            json={"code": 0, "data": {"message_id": "om-message"}},
        )

    message_id = await _clients(handler).send_text(
        recipient_open_id="ou-bd",
        text="New sample",
        idempotency_key="76666bd5-8a9b-5e5e-a404-d82d886ad259",
    )

    assert message_id == "om-message"


@pytest.mark.asyncio
async def test_send_text_to_chat_uses_chat_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.url.params["receive_id_type"] == "chat_id"
        body = json.loads(request.content)
        assert body["receive_id"] == "oc-exceptions"
        assert body["msg_type"] == "text"
        return httpx.Response(
            200,
            json={"code": 0, "data": {"message_id": "om-exception"}},
        )

    message_id = await _clients(handler).send_text_to_chat(
        chat_id="oc-exceptions",
        text="Precheck failed",
        idempotency_key="exception-key",
    )

    assert message_id == "om-exception"


@pytest.mark.asyncio
async def test_send_card_uses_interactive_message_type() -> None:
    card = {
        "header": {"title": {"tag": "plain_text", "content": "Sample"}},
        "elements": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        body = json.loads(request.content)
        assert body["receive_id"] == "ou-bd"
        assert body["msg_type"] == "interactive"
        assert body["uuid"] == "76666bd5-8a9b-5e5e-a404-d82d886ad259"
        assert json.loads(body["content"]) == card
        return httpx.Response(
            200,
            json={"code": 0, "data": {"message_id": "om-card"}},
        )

    message_id = await _clients(handler).send_card(
        recipient_open_id="ou-bd",
        card=card,
        idempotency_key="76666bd5-8a9b-5e5e-a404-d82d886ad259",
    )

    assert message_id == "om-card"


@pytest.mark.asyncio
async def test_send_card_to_chat_uses_chat_id_and_stable_uuid() -> None:
    card = {"schema": "2.0", "body": {"elements": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.url.params["receive_id_type"] == "chat_id"
        body = json.loads(request.content)
        assert body["receive_id"] == "oc-business"
        assert body["uuid"] == "76666bd5-8a9b-5e5e-a404-d82d886ad259-group"
        assert json.loads(body["content"]) == card
        return httpx.Response(
            200,
            json={"code": 0, "data": {"message_id": "om-group-card"}},
        )

    message_id = await _clients(handler).send_card_to_chat(
        chat_id="oc-business",
        card=card,
        idempotency_key="76666bd5-8a9b-5e5e-a404-d82d886ad259-group",
    )

    assert message_id == "om-group-card"


@pytest.mark.asyncio
async def test_update_card_patches_existing_interactive_message() -> None:
    card = {"schema": "2.0", "body": {"elements": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.method == "PATCH"
        assert request.url.path == "/open-apis/im/v1/messages/om-card"
        assert request.headers["Authorization"] == "Bearer tenant-token"
        body = json.loads(request.content)
        assert set(body) == {"content"}
        assert json.loads(body["content"]) == card
        return httpx.Response(200, json={"code": 0, "data": {}})

    await _clients(handler).update_card(message_id="om-card", card=card)


@pytest.mark.asyncio
async def test_delete_message_recalls_bot_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.method == "DELETE"
        assert request.url.path == "/open-apis/im/v1/messages/om-card"
        assert request.headers["Authorization"] == "Bearer tenant-token"
        return httpx.Response(200, json={"code": 0, "data": {}})

    await _clients(handler).delete_message(message_id="om-card")


@pytest.mark.asyncio
async def test_upload_message_image_uses_feishu_message_image_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.url.path == "/open-apis/im/v1/images"
        assert request.headers["Authorization"] == "Bearer tenant-token"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="image_type"' in request.content
        assert b"message" in request.content
        assert b"safe-image" in request.content
        return httpx.Response(
            200,
            json={"code": 0, "data": {"image_key": "img_v2_safe"}},
        )

    image_key = await _clients(handler).upload_message_image(
        image=b"safe-image",
        content_type="image/png",
    )

    assert image_key == "img_v2_safe"


@pytest.mark.asyncio
async def test_send_text_rejects_invalid_input_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = _clients(handler)
    with pytest.raises(ValueError, match="recipient"):
        await client.send_text(
            recipient_open_id="",
            text="New sample",
            idempotency_key="event-id",
        )
    with pytest.raises(ValueError, match="idempotency"):
        await client.send_text(
            recipient_open_id="ou-bd",
            text="New sample",
            idempotency_key="x" * 51,
        )
    assert calls == 0
