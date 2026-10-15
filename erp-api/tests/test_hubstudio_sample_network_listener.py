from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.hubstudio_sample_network_listener import (
    CURRENT_SAMPLE_GROUP_LIST_PATH,
    HubStudioSampleNetworkListener,
)
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSamplePreflight,
    HubStudioSampleTarget,
)
from erp_api.services.tiktok_sample_application_client import (
    SAMPLE_APPLICATION_SEARCH_PATH,
)

TARGET_PATH = SAMPLE_APPLICATION_SEARCH_PATH


def _payload() -> dict[str, object]:
    return {
        "code": 0,
        "request_id": "body-request-id",
        "data": {
            "sample_applications": [
                {
                    "id": "sample-1",
                    "status": "PENDING",
                    "creator": {"id": "creator-1"},
                    "product": {"id": "product-1"},
                }
            ],
            "next_page_token": "next-1",
            "total_count": 3,
        },
    }


def _preflight() -> HubStudioSamplePreflight:
    return HubStudioSamplePreflight(
        HubStudioSampleTarget(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            environment_id="1809223023",
            platform_shop_id="platform-1",
            cdp_url="http://127.0.0.1:55111",
            official_access_state="missing_scope",
        ),
        "http://127.0.0.1:55111",
    )


class FakeRequest:
    def __init__(
        self,
        method: str = "POST",
        page_url: str = "https://affiliate-us.tiktok.com/sample?shop_id=platform-1",
        post_data: str | None = None,
    ) -> None:
        self.method = method
        self.frame = SimpleNamespace(page=SimpleNamespace(url=page_url))
        self.post_data = post_data

    @property
    def headers(self):
        raise AssertionError("request headers must not be read")

    @property
    def post_data_json(self):
        raise AssertionError("request body must not be read")


class FakeResponse:
    def __init__(
        self,
        *,
        url: str | None = None,
        method: str = "POST",
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
        payload: object | None = None,
        request_id: str | None = "safe-request-id",
        page_url: str = "https://affiliate-us.tiktok.com/sample?shop_id=platform-1",
    ) -> None:
        self.url = url or (
            f"https://affiliate-us.tiktok.com{TARGET_PATH}"
            "?msToken=never-log-this&cursor=never-log-this-either"
        )
        self.request = FakeRequest(method, page_url)
        self.status = status
        self._content_type = content_type
        self._payload = _payload() if payload is None else payload
        self._request_id = request_id
        self.json_calls = 0

    async def header_value(self, name: str):
        assert name in {
            "content-type",
            "request-id",
            "x-request-id",
            "x-tts-request-id",
            "x-tt-logid",
            "x-tt-trace-id",
        }
        if name == "content-type":
            return self._content_type
        if name == "x-tt-logid":
            return self._request_id
        return None

    async def json(self):
        self.json_calls += 1
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_listener_accepts_only_exact_whitelisted_response_and_parses_page(
    capsys,
) -> None:
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    preflight = _preflight()
    listener = HubStudioSampleNetworkListener(preflight, handler)
    response = FakeResponse()

    asyncio.run(listener.handle_response(response))  # type: ignore[arg-type]

    assert response.json_calls == 1
    assert len(received) == 1
    capture = received[0]
    assert capture.target == preflight.target
    assert capture.source_type == "hubstudio_cdp"
    assert capture.page.applications[0]["id"] == "sample-1"
    assert capture.page.next_page_token == "next-1"
    assert capture.page.total_count == 3
    assert capture.page.platform_request_id == "safe-request-id"
    output = capsys.readouterr().out
    assert "hubstudio_sample_response_accepted" in output
    assert "never-log-this" not in output


def test_listener_removes_nested_credentials_before_business_handler() -> None:
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    payload = _payload()
    application = payload["data"]["sample_applications"][0]  # type: ignore[index]
    application["token"] = "response-token"  # type: ignore[index]
    application["sign"] = "response-sign"  # type: ignore[index]
    application["creator"]["cookie"] = "response-cookie"  # type: ignore[index]
    application["product"]["shop_cipher"] = "response-cipher"  # type: ignore[index]

    asyncio.run(
        HubStudioSampleNetworkListener(_preflight(), handler).handle_response(
            FakeResponse(payload=payload)
        )
    )

    captured_text = repr(received[0])
    assert "response-token" not in captured_text
    assert "response-sign" not in captured_text
    assert "response-cookie" not in captured_text
    assert "response-cipher" not in captured_text


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(url="https://affiliate-us.tiktok.com/not-approved"),
        FakeResponse(url=f"https://evil.example{TARGET_PATH}"),
        FakeResponse(method="GET"),
        FakeResponse(status=503),
        FakeResponse(content_type="text/html"),
    ],
)
def test_listener_rejects_before_reading_non_whitelisted_response(response) -> None:
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    asyncio.run(
        HubStudioSampleNetworkListener(_preflight(), handler).handle_response(response)
    )

    assert response.json_calls == 0
    assert received == []


def test_listener_rejects_invalid_json_without_leaking_payload(capsys) -> None:
    async def handler(_capture) -> None:
        raise AssertionError("invalid payload must not reach handler")

    response = FakeResponse(payload=ValueError("sensitive-response-fragment"))
    asyncio.run(
        HubStudioSampleNetworkListener(_preflight(), handler).handle_response(response)
    )

    output = capsys.readouterr().out
    assert "hubstudio_sample_listener_stopped" in output
    assert "sensitive-response-fragment" not in output


def test_listener_current_group_list_accepts_only_review_request_date() -> None:
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    common = {
        "url": (
            "https://affiliate.tiktokshopglobalselling.com"
            f"{CURRENT_SAMPLE_GROUP_LIST_PATH}"
        ),
        "page_url": (
            "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
            "sample-request?shop_id=platform-1"
        ),
        "payload": {"agg_info": [], "has_more": False},
    }
    pending_response = FakeResponse(**common)
    pending_response.request.post_data = (
        '{"tab":10,"cur_page":1,"order_params":[]}'
    )
    all_response = FakeResponse(**common)
    all_response.request.post_data = (
        '{"tab":0,"cur_page":1,"page_size":50,"order_params":[],'
        '"search_params":[{"search_key":1,"search_type":2,"value":""}]}'
    )
    relevance_response = FakeResponse(**common)
    relevance_response.request.post_data = (
        '{"tab":0,"cur_page":1,'
        '"order_params":[{"order_key":7,"order_type":2}]}'
    )
    global_application_date_response = FakeResponse(**common)
    global_application_date_response.request.post_data = (
        '{"tab":10,"cur_page":1,"page_size":50,'
        '"order_params":[{"order_key":7,"order_type":2}],'
        '"search_params":[{"search_key":1,"search_type":2,"value":""}]}'
    )
    creator_search_response = FakeResponse(**common)
    creator_search_response.request.post_data = (
        '{"tab":0,"cur_page":1,"page_size":50,"order_params":[],'
        '"search_params":[{"search_key":1,"search_type":1,"value":"creator"}]}'
    )
    local_all_response = FakeResponse(
        url=f"https://affiliate-us.tiktok.com{CURRENT_SAMPLE_GROUP_LIST_PATH}",
        page_url=(
            "https://affiliate-us.tiktok.com/affiliate/sample/"
            "sample-request?shop_id=platform-1"
        ),
        payload={"agg_info": [], "has_more": False},
    )
    local_all_response.request.post_data = (
        '{"tab":10,"cur_page":1,"page_size":50,'
        '"order_params":[],'
        '"search_params":[{"search_key":1,"search_type":2,"value":""}]}'
    )
    listener = HubStudioSampleNetworkListener(_preflight(), handler)

    asyncio.run(listener.handle_response(pending_response))
    asyncio.run(listener.handle_response(relevance_response))
    asyncio.run(listener.handle_response(creator_search_response))
    asyncio.run(listener.handle_response(all_response))
    asyncio.run(listener.handle_response(global_application_date_response))
    asyncio.run(listener.handle_response(local_all_response))

    assert pending_response.json_calls == 1
    assert relevance_response.json_calls == 0
    assert creator_search_response.json_calls == 0
    assert all_response.json_calls == 0
    assert global_application_date_response.json_calls == 0
    assert local_all_response.json_calls == 1
    assert len(received) == 2


def test_listener_ignores_responses_triggered_while_capture_is_processing() -> None:
    received = []

    async def exercise() -> None:
        async def handler(capture) -> None:
            received.append(capture)

        response = FakeResponse()
        listener = HubStudioSampleNetworkListener(_preflight(), handler)
        await listener._handler_lock.acquire()
        try:
            listener.schedule_response(response)
            await asyncio.sleep(0)
        finally:
            listener._handler_lock.release()
        await listener.wait_for_pending()

    asyncio.run(exercise())

    assert received == []


def test_listener_coalesces_responses_scheduled_before_handler_lock() -> None:
    received = []
    first = FakeResponse(request_id="first")
    duplicate = FakeResponse(request_id="duplicate")

    async def exercise() -> None:
        async def handler(capture) -> None:
            received.append(capture)
            await asyncio.sleep(0)

        listener = HubStudioSampleNetworkListener(_preflight(), handler)
        listener.schedule_response(first)
        listener.schedule_response(duplicate)
        await listener.wait_for_pending()

    asyncio.run(exercise())

    assert len(received) == 1
    assert first.json_calls == 1
    assert duplicate.json_calls == 0
