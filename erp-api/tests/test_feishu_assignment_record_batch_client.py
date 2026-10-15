import json

import httpx
import pytest

from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError


def _client(handler):
    return FeishuAssignmentRecordClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=httpx.AsyncClient(
            base_url="https://example.invalid/configure-resource",
            transport=httpx.MockTransport(handler),
        ),
    )


def _response(records):
    return httpx.Response(200, json={"code": 0, "data": {"records": records}})


@pytest.mark.asyncio
async def test_assignment_creates_use_one_batch_and_verify_number_mapping() -> None:
    calls = []

    def handler(request):
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "token", "expire": 7200},
            )
        calls.append(request)
        assert request.url.path.endswith("/records/batch_create")
        assert json.loads(request.content) == {
            "records": [
                {"fields": {"分配编号": "a", "分配BD": "BD A"}},
                {"fields": {"分配编号": "b", "分配BD": "BD B"}},
            ]
        }
        return _response(
            [
                {"record_id": "rec-a", "fields": {"分配编号": "a"}},
                {"record_id": "rec-b", "fields": {"分配编号": "b"}},
            ]
        )

    created = await _client(handler).batch_create_assignment_records(
        [{"分配编号": "a", "分配BD": "BD A"}, {"分配编号": "b", "分配BD": "BD B"}]
    )

    assert created == {"a": "rec-a", "b": "rec-b"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_assignment_updates_use_one_batch_and_reject_incomplete_response() -> (
    None
):
    def handler(request):
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "token", "expire": 7200},
            )
        assert request.url.path.endswith("/records/batch_update")
        assert len(json.loads(request.content)["records"]) == 2
        return _response([{"record_id": "rec-a"}])

    with pytest.raises(FeishuSampleError, match="incomplete"):
        await _client(handler).batch_update_assignment_records(
            [("rec-a", {"分配BD": "BD A"}), ("rec-b", {"分配BD": "BD B"})]
        )
