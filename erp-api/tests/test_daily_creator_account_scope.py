from datetime import date
from unittest.mock import AsyncMock

import pytest

from erp_api.services.feishu_creator_export_service import FEISHU_MERGED_SOURCE
from scripts.daily_valid_creator_accounts import read_accounts, select_accounts
from scripts.daily_valid_creator_shop_rows import shop_record_key


def mock_schema(client, pages):
    client.tenant_access_token = AsyncMock(return_value="unit-test-only")
    client.request_json = AsyncMock(side_effect=[
        {"data": {"app": {"name": "达人建联总表"}}},
        {"data": {"items": [{"table_id": FEISHU_MERGED_SOURCE.table_id, "name": "达人主表"}]}},
        {"data": {"items": [{"field_name": name, "type": kind} for name, kind in (
            ("同意样品日期", 5), ("BD负责人", 1), ("帐号名称", 1), ("合作店铺", 4))]}},
        *[{"data": page} for page in pages]])


@pytest.mark.asyncio
async def test_daily_reader_does_not_request_or_require_source():
    client = type("Client", (), {})()
    page = {"total": 1, "has_more": False,
        "items": [{"record_id": "r1", "fields": {"帐号名称": "@abc",
            "BD负责人": "BD", "同意样品日期": "2026-10-13", "合作店铺": ["跨境12店"]}}]}
    mock_schema(client, [page, page])
    result = await read_accounts(client)
    assert result["total"] == 1
    assert result["rows"][0]["accountName"] == "@abc"
    assert result["rows"][0]["bdOwner"] == "BD"
    assert result["rows"][0]["sampleApprovedDate"] == "2026-10-13"
    assert set(client.request_json.call_args.kwargs["json"]["field_names"]) == {
        "帐号名称", "BD负责人", "同意样品日期", "合作店铺"}
    assert result["rows"][0]["cooperationShop"] == "跨境12店"
    assert "数据来源" not in client.request_json.call_args.kwargs["json"]["field_names"]
    assert client.request_json.call_args.args[0] == "POST"
    assert client.request_json.call_args.args[1].endswith("/records/search")
    assert all(call.args[0] == "GET" for call in client.request_json.call_args_list[:3])
    assert all(call.args[0] == "POST" and call.args[1].endswith("/records/search")
               for call in client.request_json.call_args_list[3:])
    assert client.request_json.call_args.kwargs["params"] == {"page_size": 1}
    assert client.tenant_access_token.await_count == 1
    assert "view_id" not in client.request_json.call_args.kwargs["params"]
    assert set(client.request_json.call_args.kwargs["json"]) == {"field_names"}
    assert result["scope"] == "physical_table"


@pytest.mark.asyncio
async def test_reader_rejects_incomplete_or_duplicate_response():
    client = type("Client", (), {})()
    mock_schema(client, [{"total": 2, "has_more": False,
        "items": [{"record_id": "r1", "fields": {"帐号名称": "abc"}}]}])
    with pytest.raises(ValueError, match="incomplete"):
        await read_accounts(client)


def test_source_account_owner_uses_latest_nonempty_date_rule():
    rows = [{"accountName": " @ABC ", "bdOwner": "old", "sampleApprovedDate": "2026-09-01"},
            {"accountName": "abc", "bdOwner": "new", "sampleApprovedDate": "2026-10-13"}]
    result, conflicts = select_accounts(rows, (date(2026, 8, 16), date(2026, 10, 14)))
    assert result[("abc", "")]["bd"] == "new"
    assert conflicts == 1


def test_target_identity_uses_account_and_shop_without_product_line():
    fields = {"账号名称": " @ABC\u200b ", "匹配店铺": "跨境3"}
    assert shop_record_key(fields) == ("abc", "跨境3")
    assert shop_record_key(fields | {"匹配店铺": "跨境4"}) == ("abc", "跨境4")
    assert shop_record_key(fields | {"匹配店铺": "本土2店"}) == ("abc", "本土店")
    with pytest.raises(ValueError, match="exactly one"):
        shop_record_key(fields | {"匹配店铺": "跨境3；跨境4"})
