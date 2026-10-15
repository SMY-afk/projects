import json

import httpx
import pytest

from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_errors import FeishuSampleError


def _client(
    handler, *, retry_delays: tuple[float, ...] = (0.5, 1.0)
) -> FeishuSampleBatchClient:
    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource",
        transport=httpx.MockTransport(handler),
    )
    return FeishuSampleBatchClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=http_client,
        retry_delays=retry_delays,
    )


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "tenant_access_token": "tenant-token",
            "expire": 7200,
        },
    )


@pytest.mark.asyncio
async def test_list_empty_table_accepts_omitted_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        assert request.url.path.endswith("/tables/table-id/records")
        return httpx.Response(
            200,
            json={"code": 0, "data": {"has_more": False, "total": 0}},
        )

    client = _client(handler)

    records = await client.list_record_snapshots()

    assert records == ()


@pytest.mark.asyncio
async def test_list_records_can_scope_to_view_and_allowlisted_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        assert request.url.params["view_id"] == "view-id"
        assert json.loads(request.url.params["field_names"]) == ["帐号名称"]
        return httpx.Response(
            200,
            json={"code": 0, "data": {"has_more": False, "total": 0}},
        )

    records = await _client(handler).list_record_snapshots(
        view_id="view-id",
        field_names=("帐号名称",),
    )

    assert records == ()


@pytest.mark.asyncio
async def test_batch_get_records_reads_only_requested_record_ids() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        requests.append(request)
        assert request.url.path.endswith("/tables/table-id/records/batch_get")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "records": [
                        {"record_id": "rec-1", "fields": {"申请编号": "app-1"}},
                        {"record_id": "rec-2", "fields": {"申请编号": "app-2"}},
                    ]
                },
            },
        )

    records = await _client(handler).batch_get_record_snapshots(("rec-1", "rec-2"))

    assert [record.record_id for record in records] == ["rec-1", "rec-2"]
    assert json.loads(requests[0].content) == {"record_ids": ["rec-1", "rec-2"]}


@pytest.mark.asyncio
async def test_list_records_can_filter_by_modified_date_on_every_page() -> None:
    requested_pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        assert request.url.params["filter"] == (
            'CurrentValue.[最后修改时间] >= TODATE("2026-10-02")'
        )
        requested_pages.append(request.url.params.get("page_token"))
        if len(requested_pages) == 1:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "total": 2,
                        "has_more": True,
                        "page_token": "next",
                        "items": [{"record_id": "rec-1", "fields": {}}],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": 2,
                    "has_more": False,
                    "items": [{"record_id": "rec-2", "fields": {}}],
                },
            },
        )

    records = await _client(handler).list_record_snapshots(
        modified_since_date="2026-10-02"
    )

    assert [record.record_id for record in records] == ["rec-1", "rec-2"]
    assert requested_pages == [None, "next"]


@pytest.mark.asyncio
async def test_batch_create_sends_only_system_fields_and_maps_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        assert request.url.path.endswith("/tables/table-id/records/batch_create")
        assert request.headers["Authorization"] == "Bearer tenant-token"
        body = json.loads(request.content)
        assert body == {
            "records": [
                {
                    "fields": {
                        "同步键（系统）": "shop:sample-1",
                        "TK申请状态": "PENDING",
                    }
                },
                {
                    "fields": {
                        "同步键（系统）": "shop:sample-2",
                        "数据来源": "official_api",
                    }
                },
            ]
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "records": [
                        {
                            "record_id": "rec-1",
                            "fields": {"同步键（系统）": "shop:sample-1"},
                        },
                        {
                            "record_id": "rec-2",
                            "fields": {"同步键（系统）": "shop:sample-2"},
                        },
                    ]
                },
            },
        )

    client = _client(handler)

    created = await client.batch_create_records(
        [
            {"同步键（系统）": "shop:sample-1", "TK申请状态": "PENDING"},
            {"同步键（系统）": "shop:sample-2", "数据来源": "official_api"},
        ]
    )

    assert created == {"shop:sample-1": "rec-1", "shop:sample-2": "rec-2"}


@pytest.mark.asyncio
async def test_batch_update_sends_only_system_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        assert request.url.path.endswith("/tables/table-id/records/batch_update")
        body = json.loads(request.content)
        assert body == {
            "records": [
                {
                    "record_id": "rec-1",
                    "fields": {
                        "同步键（系统）": "shop:sample-1",
                        "TK申请状态": "SHIPPED",
                    },
                }
            ]
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"records": [{"record_id": "rec-1"}]},
            },
        )

    client = _client(handler)

    updated = await client.batch_update_records(
        [("rec-1", {"同步键（系统）": "shop:sample-1", "TK申请状态": "SHIPPED"})]
    )

    assert updated == ("rec-1",)


@pytest.mark.asyncio
async def test_batch_update_business_fields_sends_multiple_records_once() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        requests.append(request)
        assert request.url.path.endswith("/tables/table-id/records/batch_update")
        assert json.loads(request.content) == {
            "records": [
                {"record_id": "rec-1", "fields": {"分配BD": "BD A"}},
                {"record_id": "rec-2", "fields": {"处理状态": "待处理"}},
            ]
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"records": [{"record_id": "rec-1"}, {"record_id": "rec-2"}]},
            },
        )

    updated = await _client(handler).batch_update_business_fields(
        [("rec-1", {"分配BD": "BD A"}), ("rec-2", {"处理状态": "待处理"})]
    )

    assert updated == ("rec-1", "rec-2")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_batch_update_business_fields_rejects_system_fields() -> None:
    client = _client(
        lambda _request: (_ for _ in ()).throw(AssertionError("No API call"))
    )

    with pytest.raises(ValueError, match="business fields"):
        await client.batch_update_business_fields(
            [("rec-1", {"同步键（系统）": "shop:sample-1"})]
        )


@pytest.mark.asyncio
async def test_batch_delete_requires_exact_ids_and_verifies_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        assert request.url.path.endswith("/tables/table-id/records/batch_delete")
        assert json.loads(request.content) == {"records": ["rec-1", "rec-2"]}
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "records": [
                        {"record_id": "rec-1", "deleted": True},
                        {"record_id": "rec-2", "deleted": True},
                    ]
                },
            },
        )

    client = _client(handler)

    deleted = await client.batch_delete_records(["rec-1", "rec-2"])

    assert deleted == ("rec-1", "rec-2")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "records"),
    [
        (
            "batch_create_records",
            [{"同步键（系统）": "shop:sample-1", "分配BD": "user"}],
        ),
        ("batch_update_records", [("rec-1", {"处理状态": "跟进中"})]),
    ],
)
async def test_batch_write_rejects_business_fields_before_network(
    method_name: str,
    records: list,
) -> None:
    network_calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(500)

    client = _client(handler)

    with pytest.raises(ValueError, match="system fields"):
        await getattr(client, method_name)(records)

    assert network_calls == 0


@pytest.mark.asyncio
async def test_batch_create_fails_closed_on_incomplete_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        return httpx.Response(
            200,
            json={"code": 0, "data": {"records": []}},
        )

    client = _client(handler)

    with pytest.raises(FeishuSampleError, match="response is incomplete"):
        await client.batch_create_records([{"同步键（系统）": "shop:sample-1"}])


@pytest.mark.asyncio
async def test_batch_write_rejects_more_than_500_records() -> None:
    client = _client(lambda _request: httpx.Response(500))
    records = [{"同步键（系统）": f"shop:sample-{index}"} for index in range(501)]

    with pytest.raises(ValueError, match="between 1 and 500"):
        await client.batch_create_records(records)
