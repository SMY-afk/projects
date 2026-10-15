import asyncio
import json

import httpx
import pytest

from erp_api.services.feishu_sample_client import FeishuSampleClient, FeishuSampleError


def _client(handler) -> FeishuSampleClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=transport
    )
    return FeishuSampleClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=http_client,
    )


@pytest.mark.asyncio
async def test_create_record_returns_record_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        assert request.headers["Authorization"] == "Bearer tenant-token"
        assert (
            json.loads(request.content)["fields"]["同步键（系统）"]
            == "shop:application"
        )
        return httpx.Response(
            200, json={"code": 0, "data": {"record": {"record_id": "rec-1"}}}
        )

    client = _client(handler)
    assert await client.create_record({"同步键（系统）": "shop:application"}) == "rec-1"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_record_snapshot_includes_record_level_modifier_metadata() -> None:
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
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "record": {
                        "record_id": "rec-1",
                        "fields": {"备注": "Updated"},
                        "last_modified_by": {
                            "id": "ou-user",
                            "name": "Test User",
                        },
                        "last_modified_time": "1800000000000",
                    }
                },
            },
        )

    snapshot = await _client(handler).get_record_snapshot("rec-1")

    assert snapshot.fields == {"备注": "Updated"}
    assert snapshot.modifier_id == "ou-user"
    assert snapshot.modifier_name == "Test User"
    assert snapshot.modified_at is not None
    assert int(snapshot.modified_at.timestamp()) == 1_800_000_000


@pytest.mark.asyncio
async def test_business_update_rejects_system_field() -> None:
    client = _client(lambda request: httpx.Response(500))

    with pytest.raises(ValueError, match="business fields"):
        await client.update_business_fields("rec-1", {"TK申请状态": "PENDING"})


@pytest.mark.asyncio
async def test_system_update_rejects_business_field() -> None:
    client = _client(lambda request: httpx.Response(500))

    with pytest.raises(ValueError, match="system fields"):
        await client.update_system_fields("rec-1", {"处理状态": "跟进中"})


@pytest.mark.asyncio
async def test_tenant_token_is_cached_and_refreshed_before_expiry() -> None:
    now = [0.0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "code": 0,
                "tenant_access_token": f"tenant-token-{calls}",
                "expire": 100,
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=transport
    )
    client = FeishuSampleClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=http_client,
        clock=lambda: now[0],
        token_refresh_skew_seconds=10,
    )

    assert await client.tenant_access_token() == "tenant-token-1"
    now[0] = 89
    assert await client.tenant_access_token() == "tenant-token-1"
    now[0] = 91
    assert await client.tenant_access_token() == "tenant-token-2"
    assert calls == 2


@pytest.mark.asyncio
async def test_concurrent_token_requests_share_one_refresh() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "code": 0,
                "tenant_access_token": "tenant-token",
                "expire": 7200,
            },
        )

    client = _client(handler)
    tokens = await asyncio.gather(*(client.tenant_access_token() for _ in range(10)))

    assert tokens == ["tenant-token"] * 10
    assert calls == 1


@pytest.mark.asyncio
async def test_field_metadata_is_paginated_and_required_fields_are_validated() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
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
        assert request.headers["Authorization"] == "Bearer tenant-token"
        assert request.url.path.endswith("/tables/table-id/fields")
        if request.url.params.get("page_token") is None:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {
                                "field_id": "fld-sync",
                                "field_name": "同步键（系统）",
                                "type": 1,
                                "is_primary": True,
                            }
                        ],
                        "has_more": True,
                        "page_token": "next-page",
                        "total": 2,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "field_id": "fld-bd",
                            "field_name": "分配BD",
                            "type": 11,
                            "is_primary": False,
                        }
                    ],
                    "has_more": False,
                    "total": 2,
                },
            },
        )

    client = _client(handler)
    fields = await client.validate_required_fields({"同步键（系统）", "分配BD"})

    assert fields["同步键（系统）"].field_type == 1
    assert fields["分配BD"].field_type == 11
    assert token_calls == 1


@pytest.mark.asyncio
async def test_field_validation_fails_closed_when_required_field_is_missing() -> None:
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
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"items": [], "has_more": False, "total": 0},
            },
        )

    client = _client(handler)
    with pytest.raises(
        FeishuSampleError, match="missing required fields: 同步键（系统）"
    ):
        await client.validate_required_fields({"同步键（系统）"})


@pytest.mark.asyncio
async def test_field_transport_error_does_not_expose_credentials() -> None:
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
        raise httpx.ConnectError("failed for base-token", request=request)

    client = _client(handler)
    with pytest.raises(FeishuSampleError) as exc_info:
        await client.validate_required_fields({"同步键（系统）"})

    rendered = repr(exc_info.value)
    assert "base-token" not in rendered
    assert "tenant-token" not in rendered
    assert "app-secret" not in rendered


@pytest.mark.asyncio
async def test_create_number_field_sends_complete_definition() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "field": {
                        "field_id": "fld-score",
                        "field_name": "样品评分",
                        "type": 2,
                        "is_primary": False,
                    }
                },
            },
        )

    field = await _client(handler).create_field_definition(
        field_name="样品评分",
        field_type=2,
        ui_type="Number",
        field_property={"formatter": "0"},
    )

    assert field.field_id == "fld-score"
    assert requests[-1].method == "POST"
    assert requests[-1].url.path.endswith("/tables/table-id/fields")
    assert json.loads(requests[-1].content) == {
        "field_name": "样品评分",
        "type": 2,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    }


@pytest.mark.asyncio
async def test_create_text_field_omits_empty_property() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "field": {
                        "field_id": "fld-time-left",
                        "field_name": "样品申请剩余时间",
                        "type": 1,
                        "is_primary": False,
                    }
                },
            },
        )

    field = await _client(handler).create_field_definition(
        field_name="样品申请剩余时间",
        field_type=1,
        ui_type="Text",
        field_property={},
    )

    assert field.field_id == "fld-time-left"
    assert json.loads(requests[-1].content) == {
        "field_name": "样品申请剩余时间",
        "type": 1,
        "ui_type": "Text",
    }


@pytest.mark.asyncio
async def test_update_number_field_replaces_complete_definition() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "field": {
                        "field_id": "fld-gmv",
                        "field_name": "30日GMV",
                        "type": 2,
                        "is_primary": False,
                    }
                },
            },
        )

    field = await _client(handler).update_field_definition(
        "fld-gmv",
        field_name="30日GMV",
        field_type=2,
        ui_type="Currency",
        field_property={"formatter": "0.00", "currency_code": "USD"},
    )

    assert field.field_id == "fld-gmv"
    assert requests[-1].method == "PUT"
    assert requests[-1].url.path.endswith("/tables/table-id/fields/fld-gmv")
    assert json.loads(requests[-1].content) == {
        "field_name": "30日GMV",
        "type": 2,
        "ui_type": "Currency",
        "property": {"formatter": "0.00", "currency_code": "USD"},
    }
