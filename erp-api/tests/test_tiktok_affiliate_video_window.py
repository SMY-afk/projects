import asyncio
from datetime import date
from uuid import UUID

import pytest

from backend.app.services.tiktok_affiliate_video_window import (
    VideoWindowControlError,
    _request_matches_query_window,
    _rewrite_request_window,
    prepare_video_window_trigger,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)


def _query(resource: AffiliateCenterResource) -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=resource,
        shop_id=UUID(int=1),
        window_start=date(2026, 8, 19),
        window_end=date(2026, 8, 25),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def _creator_body() -> dict[str, object]:
    return {
        "request": {
            "requests": [
                {
                    "time_descriptor": {
                        "start": "2026-08-01",
                        "end": "2026-08-08",
                        "timezone_offset": -28_800,
                        "granularity": "7D",
                    },
                    "list_control": {"pagination": {"size": 20, "page": 3}},
                }
            ]
        }
    }


def _video_body(*, milliseconds: bool = False) -> dict[str, object]:
    scale = 1000 if milliseconds else 1
    return {
        "params": {
            "video_list_params_v2": [
                {
                    "time_descriptor": {
                        "timezone_offset": -28_800,
                        "start_time": 1_787_558_400 * scale,
                        "end_time": 1_787_731_200 * scale,
                        "time_option_type": 3,
                    },
                    "page_param": {"page_no": 4, "page_size": 20},
                }
            ]
        }
    }


def test_creator_request_is_bound_to_the_exact_selected_window() -> None:
    query = _query(AffiliateCenterResource.CREATORS)

    rewritten = _rewrite_request_window(_creator_body(), query)

    segment = rewritten["request"]["requests"][0]
    assert segment["time_descriptor"] == {
        "start": "2026-08-19",
        "end": "2026-08-26",
        "timezone_offset": -28_800,
        "granularity": "7D",
    }
    assert segment["list_control"]["pagination"] == {"size": 10, "page": 3}
    assert _request_matches_query_window(rewritten, query)


@pytest.mark.parametrize("milliseconds", [False, True])
def test_video_request_is_bound_to_the_exact_selected_window(
    milliseconds: bool,
) -> None:
    query = _query(AffiliateCenterResource.VIDEOS)

    rewritten = _rewrite_request_window(_video_body(milliseconds=milliseconds), query)

    segment = rewritten["params"]["video_list_params_v2"][0]
    scale = 1000 if milliseconds else 1
    assert segment["time_descriptor"]["start_time"] == 1_787_126_400 * scale
    assert segment["time_descriptor"]["end_time"] == 1_787_731_200 * scale
    assert segment["time_descriptor"]["time_option_type"] == 4
    assert segment["page_param"] == {"page_no": 4, "page_size": 20}
    assert _request_matches_query_window(rewritten, query)


def test_two_day_video_request_uses_the_live_ui_short_window_option() -> None:
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=UUID(int=1),
        window_start=date(2026, 10, 1),
        window_end=date(2026, 10, 2),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )

    rewritten = _rewrite_request_window(_video_body(), query)
    descriptor = rewritten["params"]["video_list_params_v2"][0]["time_descriptor"]

    assert descriptor["time_option_type"] == 1
    assert _request_matches_query_window(rewritten, query)


def test_request_matcher_rejects_a_stale_window() -> None:
    assert not _request_matches_query_window(
        _video_body(),
        _query(AffiliateCenterResource.VIDEOS),
    )
    assert not _request_matches_query_window(
        _creator_body(),
        _query(AffiliateCenterResource.CREATORS),
    )


def test_request_matcher_accepts_the_video_export_create_contract() -> None:
    body = {
        "module_type": 501,
        "transaction_video_list_params_v2": {
            "time_descriptor": {
                "timezone_offset": -28_800,
                "start_time": 1_787_126_400,
                "end_time": 1_787_731_200,
            }
        },
    }

    assert _request_matches_query_window(body, _query(AffiliateCenterResource.VIDEOS))


def test_request_matcher_does_not_confuse_post_date_with_metric_window() -> None:
    body = {
        "transaction_video_list_params_v2": {
            "time_descriptor": {
                "timezone_offset": -28_800,
                "start_time": 1_786_521_600,
                "end_time": 1_787_731_200,
            },
            "filter": {
                "video_post_date": {
                    "timezone_offset": -28_800,
                    "start_time": 1_787_126_400,
                    "end_time": 1_787_731_200,
                }
            },
        }
    }

    assert not _request_matches_query_window(body, _query(AffiliateCenterResource.VIDEOS))


@pytest.mark.parametrize("body", [None, {}, {"params": {}}, {"request": {}}])
def test_request_rewriter_rejects_an_unknown_contract(body: object) -> None:
    with pytest.raises(VideoWindowControlError):
        _rewrite_request_window(body, _query(AffiliateCenterResource.VIDEOS))


def test_prepare_captures_one_data_api_template_without_route_interception() -> None:
    class Request:
        url = (
            "https://affiliate.tiktokshopglobalselling.com"
            "/api/v1/oec/affiliate/compass/transaction/detail_list/get"
        )
        method = "POST"
        post_data_json = _video_body()

        def __init__(self) -> None:
            self.headers = {"content-type": "application/json"}

    class Page:
        def __init__(self) -> None:
            self.listeners = {}
            self.response_observed = False

        def on(self, event, listener) -> None:
            self.listeners[event] = listener

        def remove_listener(self, event, listener) -> None:
            assert listener is self.listeners[event]
            del self.listeners[event]

        async def reload(self, **_kwargs) -> None:
            request = Request()
            self.listeners["request"](request)
            self.listeners["response"](type("Response", (), {"request": request})())
            self.response_observed = True

    page = Page()
    trigger = asyncio.run(
        prepare_video_window_trigger(
            page,
            _query(AffiliateCenterResource.VIDEOS),
        )
    )

    assert trigger.replay.template_body == _video_body()
    assert page.response_observed
    assert page.listeners == {}


def test_request_route_controls_pagination_without_ui_dates() -> None:
    rewritten = _rewrite_request_window(
        _video_body(),
        _query(AffiliateCenterResource.VIDEOS),
        page_number=7,
    )
    segment = rewritten["params"]["video_list_params_v2"][0]
    assert segment["page_param"] == {"page_no": 7, "page_size": 20}


def test_followup_page_uses_the_captured_data_api_instead_of_reload() -> None:
    class Replay:
        def __init__(self) -> None:
            self.bodies = []
            self.template_body = _video_body()

        async def post(self, body) -> int:
            self.bodies.append(body)
            return 200

    class Page:
        reloads = 0

        async def reload(self, **_kwargs) -> None:
            self.reloads += 1

    page = Page()
    replay = Replay()
    trigger = asyncio.run(
        prepare_video_window_trigger(
            page,  # type: ignore[arg-type]
            _query(AffiliateCenterResource.VIDEOS),
            replay=replay,  # type: ignore[arg-type]
        )
    )
    asyncio.run(trigger.request_page(7))

    segment = replay.bodies[0]["params"]["video_list_params_v2"][0]
    assert segment["page_param"] == {"page_no": 7, "page_size": 20}
    assert page.reloads == 0
