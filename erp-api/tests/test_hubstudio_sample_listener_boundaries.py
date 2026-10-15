from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.hubstudio_sample_network_listener import (
    DEFAULT_SAMPLE_RESPONSE_PATHS,
    HubStudioSampleNetworkListener,
)
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSamplePreflight,
    HubStudioSampleTarget,
)
from erp_api.services.sample_source_policy import SampleSourcePolicyError

TARGET_PATH = next(iter(DEFAULT_SAMPLE_RESPONSE_PATHS))


def _preflight() -> HubStudioSamplePreflight:
    target = HubStudioSampleTarget(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        environment_id="1809223023",
        platform_shop_id="platform-1",
        cdp_url="http://127.0.0.1:55111",
        official_access_state="missing_scope",
    )
    return HubStudioSamplePreflight(target, target.cdp_url)


def _payload() -> dict[str, object]:
    return {
        "request_id": "body-request-id",
        "data": {
            "sample_applications": [
                {
                    "id": "sample-1",
                    "status": "PENDING",
                    "creator": {},
                    "product": {},
                }
            ],
            "total_count": 1,
        },
    }


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: object | None = None,
        request_id: str | None = "header-request-id",
        page_url: str = "https://affiliate-us.tiktok.com/sample?shop_id=platform-1",
    ) -> None:
        self.url = f"https://affiliate-us.tiktok.com{TARGET_PATH}"
        self.status = status
        self.request = SimpleNamespace(
            method="POST",
            frame=SimpleNamespace(page=SimpleNamespace(url=page_url)),
            post_data='{"tab":10,"order_params":[],"search_params":[]}',
        )
        self._payload = _payload() if payload is None else payload
        self._request_id = request_id
        self.json_calls = 0

    async def header_value(self, name: str):
        if name == "content-type":
            return "application/json"
        if name == "x-tt-logid":
            return self._request_id
        return None

    async def json(self):
        self.json_calls += 1
        return self._payload


class FakeContext:
    def __init__(self) -> None:
        self.listeners: list[tuple[str, object]] = []

    def on(self, event: str, callback) -> None:
        self.listeners.append((event, callback))


def test_invalid_payload_stops_only_this_listener_and_ignores_followups() -> None:
    stopped: list[str] = []
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    async def stop_handler(reason: str) -> None:
        stopped.append(reason)

    async def run() -> HubStudioSampleNetworkListener:
        listener = HubStudioSampleNetworkListener(
            _preflight(), handler, stop_handler=stop_handler
        )
        await listener.handle_response(FakeResponse(payload={"data": {}}))
        await listener.handle_response(FakeResponse())
        return listener

    listener = asyncio.run(run())
    assert listener.is_stopped is True
    assert listener.stop_reason == "payload_structure_changed"
    assert stopped == ["payload_structure_changed"]
    assert received == []


def test_reconciled_official_source_guard_stops_listener_before_body_read() -> None:
    async def handler(_capture) -> None:
        raise AssertionError("disabled CDP must not reach handler")

    async def source_guard() -> None:
        raise SampleSourcePolicyError(
            "official_api_reconciled", "Official source is reconciled."
        )

    response = FakeResponse()
    listener = HubStudioSampleNetworkListener(
        _preflight(), handler, source_guard=source_guard
    )
    asyncio.run(listener.handle_response(response))

    assert listener.is_stopped is True
    assert listener.stop_reason == "official_api_reconciled"
    assert response.json_calls == 0


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (FakeResponse(status=401), "session_expired"),
        (
            FakeResponse(
                page_url="https://affiliate-us.tiktok.com/sample?shop_id=other"
            ),
            "page_shop_mismatch",
        ),
        (
            FakeResponse(
                page_url="https://affiliate-us.tiktok.com/passport/login"
            ),
            "session_expired",
        ),
    ],
)
def test_login_or_runtime_shop_mismatch_stops_listener(response, reason) -> None:
    async def handler(_capture) -> None:
        raise AssertionError("stopped response must not reach handler")

    listener = HubStudioSampleNetworkListener(_preflight(), handler)
    asyncio.run(listener.handle_response(response))
    assert listener.is_stopped is True
    assert listener.stop_reason == reason
    assert response.json_calls == 0


def test_listener_uses_body_request_id_when_response_header_is_missing() -> None:
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    asyncio.run(
        HubStudioSampleNetworkListener(_preflight(), handler).handle_response(
            FakeResponse(request_id=None)
        )
    )
    assert received[0].page.platform_request_id == "body-request-id"


def test_listener_attaches_to_existing_context_response_events() -> None:
    async def handler(_capture) -> None:
        return None

    contexts = [FakeContext(), FakeContext()]
    listener = HubStudioSampleNetworkListener(_preflight(), handler)
    assert listener.attach(contexts) == 2  # type: ignore[arg-type]
    assert [item[0] for context in contexts for item in context.listeners] == [
        "response",
        "response",
    ]


def test_schedule_response_keeps_task_until_processed() -> None:
    received = []

    async def handler(capture) -> None:
        received.append(capture)

    async def run() -> None:
        listener = HubStudioSampleNetworkListener(_preflight(), handler)
        listener.schedule_response(FakeResponse())  # type: ignore[arg-type]
        await listener.wait_for_pending()

    asyncio.run(run())
    assert len(received) == 1


@pytest.mark.parametrize(
    "paths",
    [set(), {"*"}, {"/sample/*"}, {"https://example.com/sample"}, {"/sample?q=1"}],
)
def test_listener_requires_non_wildcard_exact_path_whitelist(paths) -> None:
    async def handler(_capture) -> None:
        return None

    with pytest.raises(ValueError, match="whitelist"):
        HubStudioSampleNetworkListener(
            _preflight(), handler, allowed_paths=frozenset(paths)
        )


def test_cdp_sample_modules_have_no_dom_feishu_or_credentials_dependency() -> None:
    paths = [
        Path("backend/app/services/hubstudio_sample_network_listener.py"),
        Path("src/erp_api/services/hubstudio_sample_response_parser.py"),
        Path("src/erp_api/services/hubstudio_sample_ingest_service.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).casefold()
    for forbidden in (
        "locator(",
        "text_content",
        "evaluate(",
        "connect_over_cdp",
        "async_playwright",
        "feishu",
        "app_secret",
        "access_token",
        "refresh_token",
    ):
        assert forbidden not in source
