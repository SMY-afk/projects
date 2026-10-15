from __future__ import annotations

import asyncio

import httpx

from erp_api.services.tiktok_creator_content_probe import (
    TikTokCreatorContentProbe,
    evaluate_creator_preflight,
)
from erp_api.services.tiktok_transport import TikTokTransport


def _transport(handler) -> TikTokTransport:
    return TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=0,
        http_transport=httpx.MockTransport(handler),
        clock=lambda: 1_700_000_000,
    )


def test_preflight_accepts_creator_video_scope_for_all_gate_capabilities() -> None:
    result = evaluate_creator_preflight(
        user_type=1, granted_scopes=["creator.video.write"]
    )

    assert result["userTypeValid"] is True
    assert result["readOnlyProbeReady"] is True
    assert result["publishProbeReady"] is True


def test_preflight_rejects_seller_identity_even_if_scope_text_is_present() -> None:
    result = evaluate_creator_preflight(
        user_type=0, granted_scopes=["creator.video.write"]
    )

    assert result["userTypeValid"] is False
    assert result["readOnlyProbeReady"] is False
    assert result["publishProbeReady"] is False


def test_probe_reports_only_response_shape_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"x-tts-request-id": "request-1"},
            json={
                "code": 0,
                "data": {"open_id": "secret-id", "products": [{"id": "secret"}]},
                "message": "Success",
            },
        )

    results = asyncio.run(
        TikTokCreatorContentProbe(_transport(handler)).run_read_only(
            access_token="secret-token"
        )
    )

    assert results[0]["status"] == "success"
    assert results[0]["responseShape"] == {
        "topLevelKeys": ["code", "data", "message"],
        "dataKeys": ["open_id", "products"],
        "listCounts": {"products": 1},
    }
    assert "secret-id" not in repr(results)
    assert "secret-token" not in repr(results)


def test_probe_reports_platform_code_without_message_or_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "code": 101000,
                "message": "wrong token subject with sensitive detail",
                "request_id": "request-2",
            },
        )

    results = asyncio.run(
        TikTokCreatorContentProbe(_transport(handler)).run_read_only(
            access_token="seller-token"
        )
    )

    assert results[0] == {
        "endpoint": "creator_profile",
        "status": "rejected",
        "platformCode": "101000",
        "requestId": "request-2",
        "upstreamStatus": 200,
    }
    assert "sensitive detail" not in repr(results)
