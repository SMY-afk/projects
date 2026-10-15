import asyncio
import json

import pytest

from backend.app.services.tiktok_affiliate_analytics_capture import (
    CREATOR_ANALYTICS_PATH,
    VIDEO_ANALYTICS_PATH,
    TikTokAffiliateAnalyticsSynchronizer,
)


def _creator_payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "segments": [
                {
                    "filter": {"shop_id": "shop"},
                    "list_control": {
                        "next_pagination": {
                            "has_more": False,
                            "next_page": 2,
                            "total": 0,
                            "total_page": 1,
                        },
                        "rules": [],
                    },
                    "time_descriptor": {
                        "start": "start",
                        "end": "end",
                        "timezone_offset": -7,
                    },
                    "timed_lists": [{"start": "start", "end": "end", "stats": []}],
                }
            ]
        },
    }


def _video_payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "video_list_segments_v2": [
                {
                    "time_descriptor": {
                        "start_time": 1,
                        "end_time": 2,
                        "timezone_offset": -7,
                    },
                    "total": 0,
                    "video_performances": [],
                }
            ]
        },
    }


def _creator_identity_only_payload() -> dict[str, object]:
    payload = _creator_payload()
    payload["data"]["segments"][0]["timed_lists"][0]["stats"] = [
        {"id": "creator-1", "handle": "@creator"}
    ]
    return payload


class FakeRequest:
    def __init__(self, method: str, page: object) -> None:
        self.method = method
        self.frame = type("FakeFrame", (), {"page": page})()


class FakeResponse:
    def __init__(
        self,
        path: str,
        payload: object,
        *,
        host: str = "affiliate.tiktokshopglobalselling.com",
        method: str = "POST",
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
    ) -> None:
        self.url = (
            f"https://{host}{path}"
            "?oec_seller_id=platform-shop&msToken=must-not-be-logged"
        )
        page_path = (
            "/affiliate/assets/video-analysis"
            if path == VIDEO_ANALYTICS_PATH
            else "/data/creator-analysis"
        )
        self.page = type(
            "FakePage",
            (),
            {"url": f"https://{host}{page_path}"},
        )()
        self.request = FakeRequest(method, self.page)
        self.status = status
        self._payload = payload
        self._headers = {
            "content-type": content_type,
            "x-tt-logid": "safe-request-id",
            "set-cookie": "private-cookie",
        }

    async def header_value(self, name: str) -> str | None:
        return self._headers.get(name)

    async def json(self) -> object:
        return self._payload


def test_creator_and_video_responses_reach_handler_under_shared_lock(
    capsys,
) -> None:
    async def run() -> list[tuple[str, str, str]]:
        shared_lock = asyncio.Lock()
        accepted: list[tuple[str, str, str]] = []

        async def handler(page, resource, payload, observation, context) -> None:
            assert shared_lock.locked()
            assert page is not None
            assert isinstance(payload, dict)
            assert context.platform_shop_id == "platform-shop"
            assert context.request_id == "safe-request-id"
            accepted.append(
                (
                    resource,
                    observation["payloadDiscriminator"],
                    observation["pagination"]["mode"],
                )
            )

        synchronizer = TikTokAffiliateAnalyticsSynchronizer(
            mutation_lock=shared_lock,
            payload_handler=handler,
        )
        await synchronizer.handle_response(
            FakeResponse(CREATOR_ANALYTICS_PATH, _creator_payload())
        )
        await synchronizer.handle_response(
            FakeResponse(VIDEO_ANALYTICS_PATH, _video_payload())
        )
        assert synchronizer.mutation_lock is shared_lock
        return accepted

    assert asyncio.run(run()) == [
        (
            "creators",
            "tiktok_affiliate_creator_filter_list.v1",
            "page_page_size",
        ),
        ("videos", "tiktok_affiliate_video_detail_list.v1", "unknown"),
    ]
    output = capsys.readouterr().out
    assert output.count("affiliate_analytics_response_accepted") == 2
    assert "must-not-be-logged" not in output
    assert "private-cookie" not in output
    allowed_log_keys = {
        "timestamp",
        "event",
        "request_id",
    }
    for line in output.splitlines():
        record = json.loads(line)
        assert set(record) <= allowed_log_keys


def test_us_affiliate_video_response_reaches_the_handler() -> None:
    accepted = []

    async def handler(page, resource, payload, observation, context) -> None:
        accepted.append((resource, observation["host"]))

    synchronizer = TikTokAffiliateAnalyticsSynchronizer(
        mutation_lock=asyncio.Lock(),
        payload_handler=handler,
    )

    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(
                VIDEO_ANALYTICS_PATH,
                _video_payload(),
                host="affiliate-us.tiktok.com",
            )
        )
    )

    assert accepted == [("videos", "affiliate-us.tiktok.com")]


def test_same_path_lookalike_payload_is_rejected_without_values(capsys) -> None:
    accepted: list[object] = []

    async def handler(page, resource, payload, observation, context) -> None:
        accepted.append((resource, payload, observation))

    synchronizer = TikTokAffiliateAnalyticsSynchronizer(
        mutation_lock=asyncio.Lock(),
        payload_handler=handler,
    )
    lookalike = _video_payload()
    lookalike["secret"] = "payload-secret"
    asyncio.run(
        synchronizer.handle_response(FakeResponse(CREATOR_ANALYTICS_PATH, lookalike))
    )

    assert accepted == []
    output = capsys.readouterr().out
    assert "affiliate_analytics_response_rejected" in output
    assert "payload-secret" not in output


def test_creator_identity_only_response_is_ignored_before_complete_metrics(
    capsys,
) -> None:
    accepted: list[str] = []
    failures: list[tuple[str, str, str]] = []

    async def handler(page, resource, payload, observation, context) -> None:
        accepted.append(resource)

    async def failure_handler(page, resource, status, category) -> None:
        failures.append((resource, status, category))

    async def run() -> None:
        synchronizer = TikTokAffiliateAnalyticsSynchronizer(
            mutation_lock=asyncio.Lock(),
            payload_handler=handler,
            failure_handler=failure_handler,
        )
        await synchronizer.handle_response(
            FakeResponse(
                CREATOR_ANALYTICS_PATH,
                _creator_identity_only_payload(),
            )
        )
        await synchronizer.handle_response(
            FakeResponse(CREATOR_ANALYTICS_PATH, _creator_payload())
        )

    asyncio.run(run())

    assert failures == []
    assert accepted == ["creators"]
    output = capsys.readouterr().out
    assert "affiliate_analytics_response_ignored" in output
    assert "affiliate_analytics_response_accepted" in output


@pytest.mark.parametrize(
    ("http_status", "expected_status", "expected_category"),
    [
        (401, "session_required", "session_expired"),
        (403, "failed", "http_403"),
        (429, "failed", "rate_limited"),
    ],
)
def test_terminal_http_status_is_reported_to_resource_failure_handler(
    http_status: int,
    expected_status: str,
    expected_category: str,
) -> None:
    failures: list[tuple[str, str, str]] = []

    async def failure_handler(page, resource, status, category) -> None:
        assert page is not None
        failures.append((resource, status, category))

    synchronizer = TikTokAffiliateAnalyticsSynchronizer(
        mutation_lock=asyncio.Lock(),
        failure_handler=failure_handler,
    )
    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(
                CREATOR_ANALYTICS_PATH,
                _creator_payload(),
                status=http_status,
            )
        )
    )

    assert failures == [("creators", expected_status, expected_category)]


def test_payload_structure_change_is_terminal_for_only_that_resource() -> None:
    failures: list[tuple[str, str, str]] = []

    async def failure_handler(page, resource, status, category) -> None:
        failures.append((resource, status, category))

    synchronizer = TikTokAffiliateAnalyticsSynchronizer(
        mutation_lock=asyncio.Lock(),
        failure_handler=failure_handler,
    )
    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(CREATOR_ANALYTICS_PATH, _video_payload())
        )
    )

    assert failures == [("creators", "failed", "payload_structure_changed")]


def test_unconfirmed_endpoint_is_ignored() -> None:
    calls: list[object] = []

    async def handler(page, resource, payload, observation, context) -> None:
        calls.append((resource, payload, observation))

    synchronizer = TikTokAffiliateAnalyticsSynchronizer(
        mutation_lock=asyncio.Lock(),
        payload_handler=handler,
    )
    asyncio.run(
        synchronizer.handle_response(FakeResponse("/api/other", _creator_payload()))
    )
    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(
                CREATOR_ANALYTICS_PATH,
                _creator_payload(),
                host="seller.example.test",
            )
        )
    )
    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(CREATOR_ANALYTICS_PATH, _creator_payload(), method="GET")
        )
    )

    assert calls == []


def test_scheduled_responses_are_drained() -> None:
    calls: list[str] = []

    async def run() -> None:
        async def handler(page, resource, payload, observation, context) -> None:
            calls.append(resource)

        synchronizer = TikTokAffiliateAnalyticsSynchronizer(
            mutation_lock=asyncio.Lock(),
            payload_handler=handler,
        )
        synchronizer.schedule_response(
            FakeResponse(CREATOR_ANALYTICS_PATH, _creator_payload())
        )
        await synchronizer.wait_for_pending()

    asyncio.run(run())
    assert calls == ["creators"]
