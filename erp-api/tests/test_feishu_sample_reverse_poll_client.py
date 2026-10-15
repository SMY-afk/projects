import httpx
import pytest

from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient


@pytest.mark.asyncio
async def test_reverse_poll_record_snapshots_are_paginated() -> None:
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
        page_token = request.url.params.get("page_token")
        assert request.url.params.get("automatic_fields") == "true"
        record_id = "rec-1" if page_token is None else "rec-2"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "record_id": record_id,
                            "fields": {"备注": record_id},
                            "last_modified_by": {
                                "id": f"ou-{record_id}",
                                "name": f"User {record_id}",
                            },
                            "last_modified_time": (
                                "1800000000000"
                                if page_token is None
                                else "1800000001000"
                            ),
                        }
                    ],
                    "has_more": page_token is None,
                    "page_token": "next" if page_token is None else None,
                    "total": 2,
                },
            },
        )

    client = FeishuSampleBatchClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=httpx.AsyncClient(
            base_url="https://example.invalid/configure-resource",
            transport=httpx.MockTransport(handler),
        ),
    )

    records = await client.list_record_snapshots()

    assert [record.record_id for record in records] == ["rec-1", "rec-2"]
    assert records[0].snapshot.modifier_id == "ou-rec-1"
    assert records[1].snapshot.fields == {"备注": "rec-2"}
