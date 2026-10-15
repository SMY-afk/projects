from types import SimpleNamespace

import pytest

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.logistics_feishu_client import LogisticsFeishuClient


@pytest.fixture
def live_schema_client(monkeypatch):
    # Keep the observed 33-column contract independent of implementation constants.
    names = (
        "店铺", "订单号", "实时订单状态", "实时物流状态", "订单创建时间（当地时间）",
        "当地时间的发货时间", "当地时间的真实发货时间", "实际送达时间（当地时间）",
        "创建至发货（小时）", "发货至真实发货（小时）", "真实多久送达（天）", "首次地点轨迹依据", "最新轨迹",
        "发货轨迹依据", "送达轨迹依据", "官方查询时间（北京时间）", "订单数据同步时间（北京时间）",
        "包裹号", "包裹状态", "承运商", "运单号（脱敏）", "核对说明", "导出时间（北京时间）", "物流方式",
        "ERP订单键", "预警状态", "预警节点", "快超时节点", "已超时节点", "节点预警详情",
        "首次接入飞书时间", "解除预警时间", "最近飞书同步时间",
    )
    types = {"创建至发货（小时）": 2, "发货至真实发货（小时）": 2,
             "真实多久送达（天）": 2, "预警状态": 3, "预警节点": 4}
    metadata = {name: SimpleNamespace(field_id=f"field-{index}", field_type=types.get(name, 1))
                for index, name in enumerate(names)}
    metadata["真实多久送达（天）"].field_id = "fldTzESiTP"
    client = LogisticsFeishuClient(app_id="test-app", app_secret="test-secret",
                                  base_token="test-base", table_id="test-table")

    async def list_metadata():
        return metadata

    monkeypatch.setattr(client, "list_field_metadata", list_metadata)
    return client, metadata


@pytest.mark.asyncio
async def test_existing_33_field_schema_accepts_delivery_duration_named_in_days(live_schema_client):
    client, metadata = live_schema_client

    result = await client.validate_schema()

    assert result is metadata and len(result) == 33
    assert "真实多久送达" not in result
    assert result["真实多久送达（天）"].field_id == "fldTzESiTP"
    assert result["真实多久送达（天）"].field_type == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["ERP订单键", "订单号", "官方查询时间（北京时间）"])
async def test_missing_required_field_still_rejects_schema(live_schema_client, missing):
    client, metadata = live_schema_client
    metadata.pop(missing)

    with pytest.raises(FeishuSampleError, match="schema does not match"):
        await client.validate_schema()


@pytest.mark.asyncio
async def test_delivery_duration_in_days_must_remain_numeric(live_schema_client):
    client, metadata = live_schema_client
    metadata["真实多久送达（天）"].field_type = 1

    with pytest.raises(FeishuSampleError, match="schema does not match"):
        await client.validate_schema()
