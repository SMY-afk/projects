import json

import httpx
import pytest

from erp_api.services.feishu_creator_export_service import (
    FeishuCreatorExportError,
    build_feishu_creator_export,
)


def _transport(
    source: str = "童车团队",
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        assert (
            "/apps/example2a74f860658b631683d1/tables/tblexample6a939c85/"
            in request.url.path
        )
        assert request.url.params["view_id"] == "vewRqDi0Gi"
        assert json.loads(request.url.params["field_names"]) == [
            "帐号名称",
            "BD负责人",
            "同意样品日期",
            "数据来源",
        ]
        second = "page_token" in request.url.params
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": 2,
                    "has_more": not second,
                    "page_token": None if second else "next",
                    "items": [
                        {
                            "record_id": "record-2" if second else "record-1",
                            "fields": {
                                "帐号名称": "rc-a" if second else "toy-a",
                                "BD负责人": "Carol" if second else "Alice",
                                "同意样品日期": "2026/09/20",
                                "数据来源": "遥控玩具团队" if second else source,
                            },
                        }
                    ],
                },
            },
        )

    return httpx.MockTransport(handler), requests


@pytest.mark.asyncio
async def test_merged_source_splits_two_product_lines_after_complete_pagination():
    transport, requests = _transport()

    result = await build_feishu_creator_export(
        "app-id", "app-secret", http_transport=transport
    )

    assert [table["productLine"] for table in result["tables"]] == ["童车", "遥控车"]
    assert [table["total"] for table in result["tables"]] == [1, 1]
    assert result["tables"][0]["rows"][0] == {
        "accountName": "toy-a",
        "bdOwner": "Alice",
        "sampleApprovedDate": "2026/09/20",
    }
    assert result["tables"][1]["rows"][0]["accountName"] == "rc-a"
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_merged_source_rejects_unknown_product_line():
    transport, _ = _transport("未分类")

    with pytest.raises(FeishuCreatorExportError, match="unknown data source"):
        await build_feishu_creator_export(
            "app-id", "app-secret", http_transport=transport
        )


@pytest.mark.asyncio
async def test_merged_source_excludes_only_fully_empty_placeholder():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": 2,
                    "has_more": False,
                    "items": [
                        {"record_id": "blank", "fields": {}},
                        {
                            "record_id": "valid",
                            "fields": {
                                "帐号名称": "creator-a",
                                "BD负责人": "Alice",
                                "数据来源": "童车团队",
                            },
                        },
                    ],
                },
            },
        )

    result = await build_feishu_creator_export(
        "app-id", "app-secret", http_transport=httpx.MockTransport(handler)
    )

    assert [table["total"] for table in result["tables"]] == [1, 0]
    assert result["tables"][0]["rows"][0]["accountName"] == "creator-a"


@pytest.mark.asyncio
async def test_merged_source_still_rejects_partial_row_without_source():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": 1,
                    "has_more": False,
                    "items": [
                        {"record_id": "partial", "fields": {"帐号名称": "creator-a"}}
                    ],
                },
            },
        )

    with pytest.raises(FeishuCreatorExportError, match="unknown data source"):
        await build_feishu_creator_export(
            "app-id", "app-secret", http_transport=httpx.MockTransport(handler)
        )
