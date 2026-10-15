import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from selenium.common.exceptions import StaleElementReferenceException

import backend.app.services.tiktok_sample_creator_details_selenium as collector_module
from backend.app.services.tiktok_creator_profile_performance_buffer import (
    CreatorSummaryPerformanceBuffer,
)
from backend.app.services.tiktok_sample_creator_details_collector import (
    SampleCreatorDetailsTarget,
)
from backend.app.services.tiktok_sample_creator_details_selenium import (
    TikTokSampleCreatorDetailsSeleniumCollector,
    _click_creator_avatar,
    _replace_search,
    _verified_summaries,
)
from backend.app.services.tiktok_sample_list_dom import (
    SampleListDomScore,
    sample_list_score,
    sample_score_persistence_items,
)
from erp_api.services.affiliate_creator_summary_parser import CreatorSummaryPayload
from erp_api.services.affiliate_creator_summary_repository import _updated_extensions
from erp_api.services.sample_notification_profile_builder import (
    REQUIRED_CREATOR_DETAIL_SOURCES,
    creator_details_snapshot,
)

OBSERVED_AT = datetime(2026, 9, 11, tzinfo=UTC)
URL = (
    "https://affiliate-us.tiktok.com/api/v1/oec/affiliate/creator/"
    "marketplace/profile?oec_seller_id=shop-one"
)


def _entry(method, params):
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


def test_buffers_complete_profile_response_with_external_request_id() -> None:
    buffer = CreatorSummaryPerformanceBuffer()
    entries = [
        _entry(
            "Network.requestWillBeSent",
            {
                "requestId": "cdp-1",
                "request": {
                    "url": URL,
                    "method": "POST",
                    "postData": json.dumps(
                        {"creator_oec_id": "creator-1", "profile_types": [1]}
                    ),
                },
            },
        ),
        _entry(
            "Network.responseReceived",
            {
                "requestId": "cdp-1",
                "response": {
                    "url": URL,
                    "status": 200,
                    "headers": {"X-Tt-Logid": "request-1"},
                },
            },
        ),
        _entry("Network.loadingFinished", {"requestId": "cdp-1"}),
    ]

    result = buffer.consume(
        entries,
        lambda _request_id: {"body": json.dumps({"creator_profile": {}})},
        observed_at=OBSERVED_AT,
    )

    assert len(result) == 1
    assert result[0].request_id == "request-1"
    assert result[0].request_body["profile_types"] == [1]


def test_rejects_incomplete_creator_details_batch() -> None:
    response = type(
        "Response",
        (),
        {
            "url": URL,
            "request_body": {
                "creator_oec_id": "creator-1",
                "profile_types": [1],
            },
            "payload": {
                "creator_profile": {
                    "handle": {"value": "creator_one", "is_authorized": True}
                }
            },
            "request_id": "request-1",
            "observed_at": OBSERVED_AT,
        },
    )()

    with pytest.raises(ValueError, match="completeness"):
        _verified_summaries([response], "shop-one", "creator_one")


def test_reads_visible_score_by_exact_header_instead_of_fixed_column() -> None:
    hidden = _table(
        ["Creators", "Sample score", "Fulfillment"],
        ["creator_one", "99", "90%"],
        displayed=False,
    )
    wrong_header = _table(
        ["Creators", "Sample score details", "Fulfillment"],
        ["creator_one", "77", "90%"],
    )
    reordered = _table(
        ["Fulfillment", "Creators", "Sample score"],
        ["97.73%", "creator_one", "86"],
    )
    driver = _Driver([hidden, wrong_header, reordered])

    result = sample_list_score(driver, "creator_one", observed_at=OBSERVED_AT)

    assert result == SampleListDomScore(
        overall="86",
        display_value="86",
        observed_at=OBSERVED_AT,
    )


def test_returns_none_when_sample_score_header_is_absent() -> None:
    table = _table(
        ["Creators", "Followers", "Fulfillment"],
        ["creator_one", "10,000", "90%"],
    )

    assert sample_list_score(_Driver([table]), "creator_one") is None


def test_retries_score_read_when_table_rerenders() -> None:
    table = _table(
        ["Creators", "Sample score"],
        ["creator_one", "86"],
    )
    table._stale_once = True
    driver = _Driver([table])

    result = sample_list_score(driver, "creator_one", observed_at=OBSERVED_AT)

    assert result is not None
    assert result.overall == "86"


def test_retries_avatar_click_when_row_rerenders() -> None:
    avatar = _Avatar()

    _click_creator_avatar(_AvatarDriver(avatar), "creator_one")

    assert avatar.click_attempts == 2


def test_replace_search_supports_english_and_chinese_pages() -> None:
    class Search:
        def send_keys(self, *_args) -> None:
            pass

    class Driver:
        def find_element(self, by, selector):
            assert by == collector_module.By.CSS_SELECTOR
            assert selector == collector_module.SEARCH_SELECTOR
            return Search()

    _replace_search(Driver(), "creator_one")


def test_merges_dom_score_and_provenance_with_complete_network_batch() -> None:
    summaries = [
        (_summary(kind), _response(kind))
        for kind in ("profile", "performance", "followers", "trends", "examples")
    ]
    score = SampleListDomScore("86", "86", OBSERVED_AT)

    items = sample_score_persistence_items(summaries, score)

    resources = {summary.resource_kind for summary, _request_id, _path in items}
    assert REQUIRED_CREATOR_DETAIL_SOURCES.issubset(resources)
    assert resources - REQUIRED_CREATOR_DETAIL_SOURCES == {"sample_list_dom"}
    performance = next(
        item[0] for item in items if item[0].resource_kind == "performance"
    )
    assert performance.profile_snapshot["sample_score"]["overall"] == "86"
    dom_summary, request_id, path = next(
        item for item in items if item[0].resource_kind == "sample_list_dom"
    )
    assert dom_summary.raw_data == {
        "source": "sample_request_table_dom",
        "header": "Sample score",
        "display_value": "86",
    }
    assert request_id.startswith("sample-list-dom:")
    assert path == "/affiliate/sample/sample-request"

    extensions = {}
    for summary, source_request_id, source_path in items:
        extensions = _updated_extensions(
            extensions,
            summary,
            shop_id=UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10"),
            open_id="open-1",
            username="creator_one",
            request_id=source_request_id,
            response_path=source_path,
        )
    details = extensions["creator_details_summary"]
    assert details["sources"]["sample_list_dom"]["path"] == (
        "/affiliate/sample/sample-request"
    )
    persisted = creator_details_snapshot(SimpleNamespace(extensions=extensions))
    assert persisted["sample_score"]["overall"] == "86"
    assert persisted["creator_details_complete"] is True


@pytest.mark.asyncio
async def test_collector_persists_network_and_dom_sources_in_one_batch(
    monkeypatch,
) -> None:
    summaries = [
        (_summary(kind), _response(kind))
        for kind in ("profile", "performance", "followers", "trends", "examples")
    ]
    score = SampleListDomScore("86", "86", OBSERVED_AT)
    repository = _Repository()
    driver = _CaptureDriver()
    collector = TikTokSampleCreatorDetailsSeleniumCollector(
        UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26"),
        UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10"),
        "shop-one",
        object(),
    )
    collector._repository = repository
    monkeypatch.setattr(collector_module, "_sample_handle", lambda *_args: "sample")
    monkeypatch.setattr(
        collector_module,
        "_capture_target",
        lambda *_args: ([object()], score),
    )
    monkeypatch.setattr(
        collector_module,
        "_verified_summaries",
        lambda *_args: summaries,
    )
    monkeypatch.setattr(collector_module, "_replace_search", lambda *_args: None)

    completed = await collector.capture(
        driver,
        [SampleCreatorDetailsTarget("creator_one", frozenset())],
    )

    assert completed == 1
    assert len(repository.calls) == 1
    persisted_items = repository.calls[0][2]
    assert {item[0].resource_kind for item in persisted_items} == {
        *REQUIRED_CREATOR_DETAIL_SOURCES,
        "sample_list_dom",
    }


@pytest.mark.asyncio
async def test_collector_continues_after_one_target_times_out(monkeypatch) -> None:
    summaries = [
        (_summary(kind), _response(kind))
        for kind in ("profile", "performance", "followers", "trends", "examples")
    ]
    score = SampleListDomScore("86", "86", OBSERVED_AT)
    repository = _Repository()
    driver = _CaptureDriver()
    collector = TikTokSampleCreatorDetailsSeleniumCollector(
        UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26"),
        UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10"),
        "shop-one",
        object(),
    )
    collector._repository = repository
    attempts = iter((TimeoutError("temporary"), ([object()], score)))

    def capture_target(*_args):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(collector_module, "_sample_handle", lambda *_args: "sample")
    monkeypatch.setattr(collector_module, "_capture_target", capture_target)
    monkeypatch.setattr(
        collector_module,
        "_verified_summaries",
        lambda *_args: summaries,
    )
    monkeypatch.setattr(collector_module, "_replace_search", lambda *_args: None)
    monkeypatch.setattr(collector_module, "capture_log", lambda *_args, **_kwargs: None)

    completed = await collector.capture(
        driver,
        [
            SampleCreatorDetailsTarget("creator_one", frozenset()),
            SampleCreatorDetailsTarget("creator_two", frozenset()),
        ],
    )

    assert completed == 1
    assert len(repository.calls) == 1


class _Element:
    def __init__(self, text="", *, displayed=True, children=None):
        self.text = text
        self._displayed = displayed
        self._children = children or {}

    def is_displayed(self):
        if getattr(self, "_stale_once", False):
            self._stale_once = False
            raise StaleElementReferenceException("table rerendered")
        return self._displayed

    def find_elements(self, _by, selector):
        return self._children.get(selector, [])


class _Driver:
    def __init__(self, tables):
        self._tables = tables

    def find_elements(self, _by, selector):
        return self._tables if selector == "table" else []


class _Avatar:
    def __init__(self):
        self.click_attempts = 0

    def click(self):
        self.click_attempts += 1
        if self.click_attempts == 1:
            raise StaleElementReferenceException("row rerendered")


class _AvatarDriver:
    def __init__(self, avatar):
        self.avatar = avatar

    def execute_script(self, *_args):
        return self.avatar


class _SwitchTo:
    def window(self, _handle):
        return None


class _CaptureDriver:
    switch_to = _SwitchTo()

    def execute_cdp_cmd(self, _method, _params):
        return None


class _Repository:
    def __init__(self):
        self.calls = []

    async def persist_batch(self, tenant_id, shop_id, items):
        self.calls.append((tenant_id, shop_id, items))


def _table(headers, values, *, displayed=True):
    row = _Element(
        " ".join(values),
        children={":scope > td, :scope > th": [_Element(value) for value in values]},
    )
    return _Element(
        displayed=displayed,
        children={
            "thead th": [_Element(header) for header in headers],
            "tbody tr": [row],
        },
    )


def _summary(kind):
    snapshot = {"sample_score": {"overall": "70"}} if kind == "performance" else {}
    return CreatorSummaryPayload(
        resource_kind=kind,
        platform_creator_id="creator-1",
        creator_open_id=None,
        creator_username="creator_one",
        profile_snapshot=snapshot,
        raw_data={"kind": kind},
        observed_at=OBSERVED_AT,
    )


def _response(kind):
    return type(
        "Response",
        (),
        {
            "request_id": f"request-{kind}",
            "url": f"https://affiliate-us.tiktok.com/api/{kind}",
        },
    )()
