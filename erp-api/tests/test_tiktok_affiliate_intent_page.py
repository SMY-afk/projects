import asyncio
import inspect
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services import (
    tiktok_affiliate_intent_page,
    tiktok_affiliate_page_hygiene,
)
from backend.app.services.tiktok_affiliate_intent_page import (
    IntentPageError,
    intent_query,
    prepare_intent_page,
)
from erp_api.routers import affiliate_center_stable
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntent,
)


class FakeCaptchaNode:
    async def count(self) -> int:
        return 1

    def nth(self, index: int):
        assert index == 0
        return self

    async def is_visible(self) -> bool:
        return True


class FakeCaptchaPage:
    url = "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"

    def locator(self, selector: str):
        return FakeCaptchaNode()


class FakePaginationItem:
    def __init__(self, page, index: int) -> None:
        self.page = page
        self.index = index

    async def click(self) -> None:
        self.page.clicked.append(self.index)

    async def evaluate(self, script: str) -> None:
        assert "element.click()" in script
        self.page.clicked.append(self.index)


class FakePagination:
    def __init__(self, page) -> None:
        self.page = page

    async def evaluate_all(self, script: str):
        assert "fetch" not in script.casefold()
        return [
            {"text": "1", "className": "pagination-item-active"},
            {"text": "2", "className": "pagination-item"},
        ]

    def nth(self, index: int) -> FakePaginationItem:
        return FakePaginationItem(self.page, index)


class FakeProbePage:
    def __init__(self) -> None:
        self.clicked = []
        self.reloads = 0

    def locator(self, selector: str) -> FakePagination:
        assert selector == ".kora-pagination-item"
        return FakePagination(self)

    async def reload(self, **kwargs) -> None:
        self.reloads += 1


class FakeProbeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.url = (
            "https://affiliate.tiktokshopglobalselling.com"
            "/api/v2/insights/affiliate/seller/creator/filter_list"
        )
        self.request = SimpleNamespace(method="POST")

    async def json(self):
        return self._payload


class FakeMultiResponsePage(FakeProbePage):
    def __init__(self, responses: list[FakeProbeResponse]) -> None:
        super().__init__()
        self.responses = responses
        self.handlers = []

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self.handlers.append(handler)

    def remove_listener(self, event: str, handler) -> None:
        assert event == "response"
        self.handlers.remove(handler)

    async def reload(self, **kwargs) -> None:
        await super().reload(**kwargs)
        for response in self.responses:
            for handler in list(self.handlers):
                handler(response)


class FakeDateInputs:
    def locator(self, selector: str):
        assert selector == "input"
        return self

    def nth(self, index: int):
        self.index = index
        return self

    async def input_value(self) -> str:
        return ("2026-08-01", "2026-08-07")[self.index]


class FakeRequestedWindowPage(FakeProbePage):
    def locator(self, selector: str):
        if selector == ".m4b-date-picker-range":
            return FakeDateInputs()
        return super().locator(selector)


class FakeVideoPresetLocator:
    def __init__(self, page, label: str) -> None:
        self.page = page
        self.label = label

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    async def click(self) -> None:
        self.page.clicked_labels.append(self.label)


class FakeVideoPresetPage:
    def __init__(self) -> None:
        self.clicked_labels = []

    def get_by_text(self, label, *, exact: bool):
        assert exact
        return FakeVideoPresetLocator(self, str(label))


class FakeIncompleteDateRange(FakeDateInputs):
    def __init__(self) -> None:
        self.clicks = 0
        self.values = ["2026-08-01", ""]

    async def input_value(self) -> str:
        return self.values[self.index]

    async def click(self) -> None:
        self.clicks += 1


class FakeIncompleteWindowPage(FakeProbePage):
    def __init__(self) -> None:
        super().__init__()
        self.date_range = FakeIncompleteDateRange()

    def locator(self, selector: str):
        if selector == ".m4b-date-picker-range":
            return self.date_range
        return super().locator(selector)


def _intent(resource="creators") -> AffiliateCaptureIntent:
    return AffiliateCaptureIntent(
        run_id=uuid4(),
        job_id="affiliate-intent:test",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        resource=resource,
        resource_type=f"affiliate_{resource[:-1]}",
        platform_shop_id="platform-shop-1",
        shop_timezone="America/Los_Angeles",
        currency="USD",
        window_start=datetime(2026, 8, 1, 7, tzinfo=UTC),
        window_end=datetime(2026, 8, 8, 7, tzinfo=UTC),
    )


def _creator_payload(*, complete: bool) -> dict[str, object]:
    stat = {"id": "creator-1", "handle": "@creator"}
    if complete:
        stat.update(
            {
                "revenue": {"amount": "100", "currency_code": "USD"},
                "order_cnt": 1,
            }
        )
    return {
        "code": 0,
        "message": "success",
        "data": {
            "segments": [
                {
                    "filter": {"shop_id": "platform-shop-1"},
                    "list_control": {
                        "next_pagination": {
                            "has_more": False,
                            "next_page": 2,
                            "total": 1,
                            "total_page": 1,
                        },
                        "rules": [],
                    },
                    "time_descriptor": {
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                        "timezone_offset": -7,
                    },
                    "timed_lists": [
                        {
                            "start": "2026-08-01",
                            "end": "2026-08-07",
                            "stats": [stat],
                        }
                    ],
                }
            ]
        },
    }


def test_intent_query_restores_the_shop_local_inclusive_window() -> None:
    query = intent_query(_intent())

    assert query.window_start.isoformat() == "2026-08-01"
    assert query.window_end.isoformat() == "2026-08-07"
    assert query.shop_timezone == "America/Los_Angeles"


def test_missing_page_and_captcha_fail_before_run_can_start() -> None:
    with pytest.raises(IntentPageError) as missing:
        asyncio.run(prepare_intent_page([SimpleNamespace(pages=[])], _intent()))
    assert missing.value.category == "target_page_missing"

    with pytest.raises(IntentPageError) as captcha:
        asyncio.run(
            prepare_intent_page(
                [SimpleNamespace(pages=[FakeCaptchaPage()])],
                _intent(),
            )
        )
    assert captcha.value.category == "captcha"


def test_listener_startup_opens_each_missing_affiliate_resource_page() -> None:
    opened = []

    class Page:
        url = "about:blank"

        async def goto(self, url, **kwargs):
            opened.append((url, kwargs))
            self.url = url

    class Context:
        def __init__(self) -> None:
            self.pages = []

        async def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

    context = Context()

    asyncio.run(
        tiktok_affiliate_page_hygiene.ensure_affiliate_resource_pages([context])
    )

    assert [item[0] for item in opened] == [
        "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis",
        "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis",
    ]
    assert all(item[1]["wait_until"] == "domcontentloaded" for item in opened)


def test_creator_detail_page_is_not_used_for_report_export() -> None:
    detail_page = SimpleNamespace(
        url=(
            "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
            "?creator_id=creator-1&shop_id=platform-shop-1"
        )
    )
    list_page = SimpleNamespace(
        url=(
            "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
            "?shop_id=platform-shop-1"
        )
    )

    assert not tiktok_affiliate_intent_page._is_intent_resource_page(
        detail_page,
        "/data/creator-analysis",
        "creators",
    )
    assert tiktok_affiliate_intent_page._is_intent_resource_page(
        list_page,
        "/data/creator-analysis",
        "creators",
    )


def test_current_video_analysis_path_is_used_for_report_export() -> None:
    page = SimpleNamespace(
        url=(
            "https://affiliate.tiktokshopglobalselling.com/insights/video-analysis"
            "?shop_id=platform-shop-1"
        )
    )

    assert tiktok_affiliate_intent_page._is_intent_resource_page(
        page,
        "/affiliate/assets/video-analysis",
        "videos",
    )


def test_current_video_analysis_path_identifies_browser_shop() -> None:
    page = SimpleNamespace(
        url=(
            "https://affiliate.tiktokshopglobalselling.com/insights/video-analysis"
            "?shop_region=US&shop_id=9121478993551097445"
        )
    )

    assert tiktok_affiliate_intent_page.browser_platform_shop_ids([page]) == {
        "9121478993551097445"
    }


def test_api_and_arq_layers_do_not_own_browser_state() -> None:
    route_source = inspect.getsource(affiliate_center_stable)
    page_source = inspect.getsource(tiktok_affiliate_intent_page)

    assert "playwright" not in route_source.casefold()
    assert "cookie" not in route_source.casefold()
    assert "dynamic signature" not in route_source.casefold()
    assert "request.headers" not in page_source
    assert "request.post_data" not in page_source


def test_creator_probe_refreshes_the_existing_page() -> None:
    page = FakeProbePage()

    asyncio.run(tiktok_affiliate_intent_page._trigger_probe_request(page, "creators"))

    assert page.clicked == []
    assert page.reloads == 1


@pytest.mark.parametrize("complete_first", [False, True])
def test_creator_probe_selects_complete_metrics_regardless_of_response_order(
    complete_first: bool,
) -> None:
    complete = FakeProbeResponse(_creator_payload(complete=True))
    identity_only = FakeProbeResponse(_creator_payload(complete=False))
    responses = (
        [complete, identity_only] if complete_first else [identity_only, complete]
    )
    page = FakeMultiResponsePage(responses)

    selected = asyncio.run(tiktok_affiliate_intent_page._probe_page(page, "creators"))

    assert selected is complete
    assert page.reloads == 1
    assert page.handlers == []


def test_creator_probe_reports_sparse_only_responses_as_payload_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakeMultiResponsePage([FakeProbeResponse(_creator_payload(complete=False))])
    monkeypatch.setitem(
        tiktok_affiliate_intent_page._probe_page.__globals__,
        "RESPONSE_TIMEOUT_MS",
        20,
    )

    with pytest.raises(IntentPageError) as error:
        asyncio.run(tiktok_affiliate_intent_page._probe_page(page, "creators"))

    assert error.value.category == "payload_structure_changed"
    assert page.handlers == []


def test_creator_window_uses_the_page_date_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakeRequestedWindowPage()
    selected = []

    async def select_creator_window(_, start, end):
        selected.append((start, end))

    monkeypatch.setattr(
        tiktok_affiliate_intent_page,
        "_select_creator_window",
        select_creator_window,
    )
    trigger = asyncio.run(
        tiktok_affiliate_intent_page._prepare_trigger(page, intent_query(_intent()))
    )

    asyncio.run(trigger())

    assert selected == [(date(2026, 8, 1), date(2026, 8, 7))]
    assert page.clicked == [0]


def test_creator_window_is_idempotent_when_requested_dates_are_already_selected() -> (
    None
):
    class Input:
        def __init__(self, value: str) -> None:
            self.value = value

        async def input_value(self) -> str:
            return self.value

    class Inputs:
        def __init__(self) -> None:
            self.values = [Input("2026-09-09"), Input("2026-09-09")]

        def nth(self, index: int) -> Input:
            return self.values[index]

    class Picker:
        async def wait_for(self, **kwargs) -> None:
            assert kwargs == {"state": "visible", "timeout": 30_000}

        def locator(self, selector: str) -> Inputs:
            assert selector == "input"
            return Inputs()

        async def click(self) -> None:
            raise AssertionError(
                "an already selected creator window must not be reopened"
            )

    class Page:
        def locator(self, selector: str) -> Picker:
            assert selector == ".m4b-date-picker-range"
            return Picker()

    asyncio.run(
        tiktok_affiliate_intent_page._select_creator_window(
            Page(),
            date(2026, 9, 9),
            date(2026, 9, 9),
        )
    )


def test_creator_trigger_reselects_window_when_single_page_has_no_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakeRequestedWindowPage()
    selected = []
    trigger_attempts = 0

    async def select_creator_window(_, start, end):
        selected.append((start, end))

    async def trigger_first_page(_):
        nonlocal trigger_attempts
        trigger_attempts += 1
        raise IntentPageError("request_timeout")

    monkeypatch.setattr(
        tiktok_affiliate_intent_page,
        "_select_creator_window",
        select_creator_window,
    )
    monkeypatch.setattr(
        tiktok_affiliate_intent_page,
        "_trigger_creator_first_page",
        trigger_first_page,
    )
    trigger = asyncio.run(
        tiktok_affiliate_intent_page._prepare_trigger(page, intent_query(_intent()))
    )

    asyncio.run(trigger())

    assert trigger_attempts == 1
    assert selected == [
        (date(2026, 8, 1), date(2026, 8, 7)),
        (date(2026, 8, 1), date(2026, 8, 7)),
    ]


def test_video_thirty_day_intent_defers_date_control_to_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakeVideoPresetPage()
    intent = replace(
        _intent("videos"),
        window_start=datetime(2026, 7, 9, 7, tzinfo=UTC),
        window_end=datetime(2026, 8, 8, 7, tzinfo=UTC),
    )
    trigger = asyncio.run(
        tiktok_affiliate_intent_page._prepare_trigger(page, intent_query(intent))
    )
    asyncio.run(trigger())


def test_video_custom_window_defers_date_control_to_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakeVideoPresetPage()
    intent = replace(
        _intent("videos"),
        window_end=datetime(2026, 8, 6, 7, tzinfo=UTC),
    )
    trigger = asyncio.run(
        tiktok_affiliate_intent_page._prepare_trigger(page, intent_query(intent))
    )
    asyncio.run(trigger())


def test_us_video_page_uses_an_exact_data_api_window_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        url=(
            "https://affiliate-us.tiktok.com/affiliate/assets/video-analysis"
            "?shop_region=US&shop_id=platform-shop-1"
        )
    )
    prepared = []

    async def prepare_window(candidate, query):
        prepared.append((candidate, query))
        return "exact-trigger"

    monkeypatch.setattr(
        tiktok_affiliate_intent_page,
        "prepare_video_window_trigger",
        prepare_window,
    )
    query = intent_query(_intent("videos"))
    trigger = asyncio.run(
        tiktok_affiliate_intent_page._prepare_trigger(
            page,
            query,
        )
    )

    assert trigger == "exact-trigger"
    assert prepared == [(page, query)]


def test_prepare_intent_does_not_fan_out_when_selected_page_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = SimpleNamespace(
        url="https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
    )
    second = SimpleNamespace(
        url="https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
    )

    class Response:
        status = 200
        url = "https://affiliate.tiktokshopglobalselling.com/api?shop_region=platform-shop-1"

        async def json(self):
            return {"code": 0}

    async def no_security_failure(page):
        return None

    async def probe(page, resource):
        return Response()

    async def prepare_trigger(page, query):
        if page is first:
            raise IntentPageError("window_not_settable")

        async def trigger() -> None:
            return None

        return trigger

    monkeypatch.setattr(
        tiktok_affiliate_intent_page,
        "page_security_failure",
        no_security_failure,
    )
    monkeypatch.setattr(tiktok_affiliate_intent_page, "_probe_page", probe)
    monkeypatch.setattr(
        tiktok_affiliate_intent_page,
        "platform_shop_id",
        lambda _: "platform-shop-1",
    )
    monkeypatch.setattr(
        tiktok_affiliate_intent_page, "_prepare_trigger", prepare_trigger
    )

    with pytest.raises(IntentPageError) as error:
        asyncio.run(
            prepare_intent_page([SimpleNamespace(pages=[first, second])], _intent())
        )

    assert error.value.category == "window_not_settable"
    assert error.value.page is first
