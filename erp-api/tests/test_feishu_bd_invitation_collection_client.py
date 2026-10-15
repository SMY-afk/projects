import json

import httpx
import pytest

from erp_api.services.feishu_bd_invitation_collection_client import (
    FeishuBdInvitationCollectionClient,
)


def _client(handler) -> FeishuBdInvitationCollectionClient:
    return FeishuBdInvitationCollectionClient(
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
async def test_batch_update_remarks_writes_only_remark_field() -> None:
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
        assert request.url.path.endswith("/tables/table-id/records/batch_update")
        assert json.loads(request.content) == {
            "records": [
                {
                    "record_id": "rec-1",
                    "fields": {"备注": "命中：AI邀约表；按创建时间保存24小时"},
                }
            ]
        }
        return httpx.Response(
            200,
            json={"code": 0, "data": {"records": [{"record_id": "rec-1"}]}},
        )

    updated = await _client(handler).batch_update_remarks(
        [("rec-1", "命中：AI邀约表；按创建时间保存24小时")]
    )

    assert updated == ("rec-1",)


@pytest.mark.asyncio
async def test_batch_update_remarks_rejects_blank_text_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ValueError, match="remark update"):
        await _client(handler).batch_update_remarks([("rec-1", " ")])

    assert calls == 0


@pytest.mark.asyncio
async def test_batch_create_invitations_creates_one_record_per_creator() -> None:
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
        assert request.url.path.endswith("/tables/table-id/records/batch_create")
        assert json.loads(request.content) == {
            "records": [
                {
                    "fields": {
                        "达人ID": "creator-one",
                        "BD负责人": "Alice",
                        "原提交人": "Original User",
                    }
                },
                {
                    "fields": {
                        "达人ID": "creator-two",
                        "BD负责人": "Alice",
                        "原提交人": "Original User",
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
                        {"record_id": "rec-1"},
                        {"record_id": "rec-2"},
                    ]
                },
            },
        )

    created = await _client(handler).batch_create_invitations(
        [
            ("creator-one", "Alice", "Original User"),
            ("creator-two", "Alice", "Original User"),
        ]
    )

    assert created == ("rec-1", "rec-2")


@pytest.mark.asyncio
async def test_batch_update_split_records_writes_creator_and_submitter_fields() -> None:
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
        assert json.loads(request.content) == {
            "records": [
                {
                    "record_id": "rec-1",
                    "fields": {
                        "达人ID": "creator-one",
                        "原提交人": "Original User",
                    },
                }
            ]
        }
        return httpx.Response(
            200,
            json={"code": 0, "data": {"records": [{"record_id": "rec-1"}]}},
        )

    updated = await _client(handler).batch_update_split_records(
        [("rec-1", "creator-one", "Original User")]
    )

    assert updated == ("rec-1",)
