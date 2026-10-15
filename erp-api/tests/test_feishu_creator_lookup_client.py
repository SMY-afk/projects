import json

import httpx
import pytest

from erp_api.services.feishu_creator_lookup_client import FeishuCreatorLookupClient


def _client(handler) -> FeishuCreatorLookupClient:
    return FeishuCreatorLookupClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=httpx.AsyncClient(
            base_url="https://example.invalid/configure-resource",
            transport=httpx.MockTransport(handler),
        ),
    )


@pytest.mark.asyncio
async def test_match_creator_ids_uses_exact_search_and_paginates() -> None:
    search_requests = []

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
        assert request.url.path.endswith("/tables/table-id/records/search")
        body = json.loads(request.content)
        search_requests.append(body)
        if request.url.params.get("page_token") is None:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [{"fields": {"达人ID": "@Creator-One"}}],
                        "has_more": True,
                        "page_token": "page-2",
                        "total": 2,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"fields": {"达人ID": "creator-two"}}],
                    "has_more": False,
                    "total": 2,
                },
            },
        )

    matches = await _client(handler).match_creator_ids(
        {"CREATOR-ONE", "creator-two", "missing"},
        field_name="达人ID",
    )

    assert matches == frozenset({"creator-one", "creator-two"})
    assert len(search_requests) == 2
    values = {
        condition["value"][0]
        for condition in search_requests[0]["filter"]["conditions"]
    }
    assert values == {
        "creator-one",
        "@creator-one",
        "creator-two",
        "@creator-two",
        "missing",
        "@missing",
    }


@pytest.mark.asyncio
async def test_match_creator_ids_skips_network_for_empty_input() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    matches = await _client(handler).match_creator_ids(set(), field_name="达人ID")

    assert matches == frozenset()
    assert calls == 0
