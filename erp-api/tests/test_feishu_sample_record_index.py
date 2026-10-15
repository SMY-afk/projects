from __future__ import annotations

import httpx
import pytest

from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_record_index import (
    build_record_sync_key_map,
)


def _record(record_id: str, sync_key: object) -> dict[str, object]:
    return {"record_id": record_id, "fields": {"同步键（系统）": sync_key}}


@pytest.mark.asyncio
async def test_empty_table_accepts_omitted_items() -> None:
    async def fetch_page(_page_token):
        return {"has_more": False, "total": 0}

    mapping = await build_record_sync_key_map(fetch_page)

    assert mapping == {}


@pytest.mark.asyncio
async def test_client_builds_complete_paginated_sync_key_map() -> None:
    token_calls = 0
    record_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, record_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        record_calls += 1
        assert request.headers["Authorization"] == "Bearer tenant-token"
        assert request.url.params["page_size"] == "500"
        if request.url.params.get("page_token") is None:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            _record("rec-1", "shop:sample-1"),
                            _record("blank", ""),
                        ],
                        "has_more": True,
                        "page_token": "next-page",
                        "total": 3,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [_record("rec-2", "shop:sample-2")],
                    "has_more": False,
                    "total": 3,
                },
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource",
        transport=httpx.MockTransport(handler),
    )
    client = FeishuSampleClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=http_client,
    )

    mapping = await client.list_record_sync_key_map()

    assert mapping == {
        "shop:sample-1": "rec-1",
        "shop:sample-2": "rec-2",
    }
    assert token_calls == 1
    assert record_calls == 2


@pytest.mark.asyncio
async def test_duplicate_sync_key_fails_closed() -> None:
    pages = iter(
        (
            {
                "items": [_record("rec-1", "duplicate")],
                "has_more": True,
                "page_token": "next-page",
                "total": 2,
            },
            {
                "items": [_record("rec-2", "duplicate")],
                "has_more": False,
                "total": 2,
            },
        )
    )

    async def fetch_page(_page_token):
        return next(pages)

    with pytest.raises(FeishuSampleError, match="sync key is duplicated"):
        await build_record_sync_key_map(fetch_page)


@pytest.mark.asyncio
async def test_incomplete_record_total_fails_closed() -> None:
    async def fetch_page(_page_token):
        return {
            "items": [_record("rec-1", "shop:sample-1")],
            "has_more": False,
            "total": 2,
        }

    with pytest.raises(FeishuSampleError, match="total is incomplete"):
        await build_record_sync_key_map(fetch_page)


@pytest.mark.asyncio
async def test_repeated_page_token_fails_closed() -> None:
    async def fetch_page(_page_token):
        return {
            "items": [],
            "has_more": True,
            "page_token": "same-token",
            "total": 0,
        }

    with pytest.raises(FeishuSampleError, match="pagination is incomplete"):
        await build_record_sync_key_map(fetch_page)
