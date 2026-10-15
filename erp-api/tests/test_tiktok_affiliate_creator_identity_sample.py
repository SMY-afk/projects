import asyncio
from types import SimpleNamespace
from typing import ClassVar

from backend.app.services import tiktok_affiliate_creator_identity_sample as sample


class _Request:
    method = "POST"
    post_data_json: ClassVar = {"request": {"requests": []}}


class _Response:
    url = "https://affiliate.tiktokshopglobalselling.com/api/v2/insights/affiliate/seller/creator/filter_list"
    status = 200
    request = _Request()

    async def json(self):
        return {
            "code": 0,
            "data": {
                "segments": [
                    {
                        "list_control": {
                            "next_pagination": {"has_more": False, "total": 712}
                        }
                    }
                ]
            },
        }


class _ReloadFallbackPage:
    def __init__(self) -> None:
        self.listener = None
        self.reloads = 0

    def on(self, event, listener):
        assert event == "response"
        self.listener = listener

    def remove_listener(self, event, listener):
        assert event == "response"
        assert listener is self.listener

    async def evaluate(self, script):
        assert script == "location.reload()"
        self.reloads += 1
        self.listener(_Response())


def test_reconciliation_page_limit_covers_the_full_creator_total() -> None:
    assert sample.creator_identity_page_limit(6_632) == 34
    assert sample.creator_identity_page_limit(8_349) == 42


def test_source_total_uses_bound_window_trigger_without_page_reload(
    monkeypatch,
) -> None:
    page = object()
    calls = []

    async def trigger() -> None:
        calls.append("triggered")

    async def perform_and_wait(actual_page, action):
        assert actual_page is page
        assert action is trigger
        await action()
        return {
            "data": {
                "segments": [
                    {
                        "list_control": {
                            "next_pagination": {
                                "has_more": False,
                                "total": 210,
                            }
                        }
                    }
                ]
            }
        }

    monkeypatch.setattr(sample, "_perform_and_wait", perform_and_wait)

    total = asyncio.run(sample.creator_source_total(page, trigger))

    assert total == 210
    assert calls == ["triggered"]


def test_list_request_reloads_when_current_first_page_click_emits_no_request(
    monkeypatch,
) -> None:
    page = _ReloadFallbackPage()

    async def no_op_trigger() -> None:
        return None

    monkeypatch.setattr(sample, "LIST_RESPONSE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(sample, "require_affiliate_payload", lambda *args: None)

    url, body = asyncio.run(sample._list_request(page, no_op_trigger))

    assert url == _Response.url
    assert body == _Request.post_data_json
    assert page.reloads == 1


def test_full_identity_sample_uses_bound_window_trigger(monkeypatch) -> None:
    page = object()
    trigger = object()
    calls = []

    async def list_request(actual_page, action):
        calls.append((actual_page, action))
        return "https://example.test/list", {"request": {}}

    async def fetch(actual_page, url, body):
        return {"page": body["page"]}

    def batch_body(body, page_index):
        return {"page": page_index}

    def parse(payload, *, query):
        return [
            SimpleNamespace(
                username_normalized=f"creator-{payload['page']}", avatar_url="avatar"
            )
        ]

    monkeypatch.setattr(sample, "_list_request", list_request)
    monkeypatch.setattr(sample, "_fetch_identity_batch", fetch)
    monkeypatch.setattr(sample, "_batch_request_body", batch_body)
    monkeypatch.setattr(sample, "parse_creator_page_payload", parse)
    monkeypatch.setattr(sample, "pagination", lambda payload: (payload["page"] == 0, 2))

    result = asyncio.run(
        sample.collect_creator_identity_sample(
            page,
            SimpleNamespace(shop_id="shop-1"),
            "tenant-1",
            max_pages=2,
            request_interval=0,
            trigger=trigger,
            collect_all=True,
        )
    )

    assert calls == [(page, trigger)]
    assert [record.username_normalized for record in result.records] == [
        "creator-0",
        "creator-1",
    ]
    assert result.expected_total == 2


def test_full_identity_sample_reuses_source_captured_before_export(monkeypatch) -> None:
    page = object()
    calls = []
    first_payload = {"page": 0}
    source = sample.CreatorIdentitySource(
        request_url="https://example.test/list",
        request_body={"request": {}},
        first_payload=first_payload,
        expected_total=2,
    )

    async def list_request(*args):
        raise AssertionError("captured source must not trigger the page again")

    async def fetch(actual_page, url, body):
        calls.append((actual_page, url, body))
        return {"page": body["page"]}

    def batch_body(body, page_index):
        return {"page": page_index}

    def parse(payload, *, query):
        return [
            SimpleNamespace(
                username_normalized=f"creator-{payload['page']}",
                avatar_url="avatar",
            )
        ]

    monkeypatch.setattr(sample, "_list_request", list_request)
    monkeypatch.setattr(sample, "_fetch_identity_batch", fetch)
    monkeypatch.setattr(sample, "_batch_request_body", batch_body)
    monkeypatch.setattr(sample, "parse_creator_page_payload", parse)
    monkeypatch.setattr(sample, "pagination", lambda payload: (payload["page"] == 0, 2))

    result = asyncio.run(
        sample.collect_creator_identity_sample(
            page,
            SimpleNamespace(shop_id="shop-1"),
            "tenant-1",
            max_pages=2,
            request_interval=0,
            collect_all=True,
            source=source,
        )
    )

    assert calls == [(page, "https://example.test/list", {"page": 1})]
    assert [record.username_normalized for record in result.records] == [
        "creator-0",
        "creator-1",
    ]
