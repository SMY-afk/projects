from datetime import UTC, datetime

from erp_api.services.logistics_feishu_fields import EXCEL_FIELDS, RED, field_definition
from erp_api.services.logistics_feishu_plan import same_value
from erp_api.services.logistics_feishu_projection import hours, project_order


def test_local_times_and_overlapping_warning_nodes_match_excel_semantics():
    row = project_order({"key": "tenant:shop:order", "timezone": "America/Los_Angeles", "shopName": "Shop",
                         "orderNumber": "982740775181726442", "orderCreatedAt": "2026-10-07T08:00:00Z",
                         "platformStatus": "AWAITING_COLLECTION", "erpSyncedAt": "2026-10-13T01:00:00Z"},
                        {"checkedAt": "2026-10-13T02:00:00Z", "firstLocationAt": "2026-10-07T11:00:00Z",
                         "firstLocationDescription": "Arrived at the CHINO carrier's facility.",
                         "shippingType": "TIKTOK", "fulfillmentType": "FULFILLMENT_BY_TIKTOK",
                         "events": [{"status": "ready_for_collection", "actionCode": "20101",
                                     "occurredAt": "2026-10-07T09:00:00Z", "description": "Order packed and ready for pickup."}]},
                        {"uncollected_48h": 3600, "undelivered_77h": -7200}, datetime(2026, 10, 13, tzinfo=UTC))
    assert set(EXCEL_FIELDS) <= row.keys()
    assert row["订单创建时间（当地时间）"] == "2026-10-07 01:00:00"
    assert row["创建至发货（小时）"] == 1
    assert row["发货至真实发货（小时）"] == 3
    assert row["首次地点轨迹依据"] == "已到达承运商的CHINO仓储场所。"
    assert row["最新轨迹"] == "订单已打包，正在等待承运商揽收。"
    assert row["物流方式"] == "FBT物流"
    assert row["预警状态"] == RED
    assert row["快超时节点"] == "未送达" and row["已超时节点"] == "未真实发货"
    assert row["官方查询时间（北京时间）"] == "2026-10-13 10:00:00"
    assert row["订单数据同步时间（北京时间）"] == "2026-10-13 09:00:00"
    assert row["导出时间（北京时间）"] == ""


def test_elapsed_time_crosses_dst_using_real_instants():
    assert hours("2026-11-01T08:30:00Z", "2026-11-01T10:30:00Z") == 2
    assert hours("2026-11-01T08:30:00Z", None) is None


def test_delivery_duration_uses_official_delivery_minus_creation_and_stays_empty_until_delivered():
    order = {"key": "tenant:shop:order", "timezone": "America/Los_Angeles", "shopName": "Shop",
             "orderNumber": "order", "orderCreatedAt": "2026-11-01T08:30:00Z", "platformStatus": "DELIVERED"}
    live = {"deliveredAt": "2026-11-01T10:30:00Z", "firstLocationAt": "2026-11-01T09:30:00Z"}
    row = project_order(order, live, {}, datetime(2026, 11, 2, tzinfo=UTC))
    assert row["真实多久送达（天）"] == 0.083333
    assert EXCEL_FIELDS.index("真实多久送达（天）") + 1 == EXCEL_FIELDS.index("首次地点轨迹依据")
    assert field_definition("真实多久送达（天）")["type"] == 2
    assert same_value("真实多久送达（天）", "2.000000", 2)
    live.pop("deliveredAt")
    assert project_order(order, live, {}, datetime(2026, 11, 2, tzinfo=UTC))["真实多久送达（天）"] is None
    live["deliveredAt"] = "2026-11-02T20:30:00Z"
    assert project_order(order, live, {}, datetime(2026, 11, 2, tzinfo=UTC))["真实多久送达（天）"] == 1.5
