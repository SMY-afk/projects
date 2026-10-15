"""Project official snapshots into the same local times and durations as Excel."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from erp_api.services.logistics_feishu_fields import (
    EXCEL_FIELDS,
    NODE_NAMES,
    RED,
    RESOLVED,
    YELLOW,
)
from erp_api.services.logistics_feishu_translation import translate

LABELS = {
    "AWAITING_SHIPMENT": "待发货", "AWAITING_COLLECTION": "待揽收", "PARTIALLY_SHIPPING": "部分发货",
    "IN_TRANSIT": "运输中", "DELIVERED": "已送达", "COMPLETED": "已完成", "CANCELLED": "已取消",
    "order_created": "订单已创建", "ready_for_collection": "已打包待揽收", "info_received": "已收到物流信息",
    "picked_up": "已揽收", "in_transit": "运输中", "out_for_delivery": "派送中", "delivered": "已送达",
    "exception": "物流异常", "returned": "已退回", "cancelled": "已取消",
}


def instant(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Logistics timestamps must contain a timezone")
    return result


def display_time(value, timezone="Asia/Shanghai"):
    return instant(value).astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def hours(start, end):
    if not start or not end:
        return None
    # Excel displays whole seconds and measures elapsed time across DST changes.
    return round((instant(end).astimezone(UTC).replace(microsecond=0) -
                  instant(start).astimezone(UTC).replace(microsecond=0)).total_seconds() / 3600, 6)


def days(start, end):
    elapsed = hours(start, end)
    return round(elapsed / 24, 6) if elapsed is not None else None


def shipping_method(shipping, fulfillment):
    if shipping == "SELLER":
        return "物流方式待确认" if fulfillment == "FULFILLMENT_BY_TIKTOK" else "商家物流"
    if shipping == "TIKTOK":
        return {"FULFILLMENT_BY_SELLER": "TikTok物流", "FULFILLMENT_BY_TIKTOK": "FBT物流"}.get(
            fulfillment, "平台物流（具体类型待确认）")
    return "物流方式待确认"


def project_order(order, live, flags, now):
    timezone = order["timezone"]
    if not timezone:
        raise ValueError("A shop timezone is required for Feishu local timestamps")
    created = live.get("orderCreatedAt") or order["orderCreatedAt"]
    events = sorted(live.get("events") or [], key=lambda item: instant(item["occurredAt"]))
    packed = next((e for e in events if e["status"] == "ready_for_collection" or e["actionCode"] == "20101"
                   or "order packed and ready for pickup" in (e.get("description") or "").lower()
                   or "订单已打包" in (e.get("description") or "")), {})
    packages = live.get("packages") if "packages" in live else order.get("packages", [])
    shipping = live.get("shippingType") or order.get("shippingType")
    fulfillment = live.get("fulfillmentType") or order.get("fulfillmentType")
    latest = events[-1] if events else {}
    tracking = live.get("trackingStatus")
    notes = [f"店铺时区：{timezone}", *(live.get("milestoneNotes") or [])]
    if not live:
        notes.append("轨迹信息等待后台官方查询补齐；节点时间为空不代表已核实未完成")
    if not packed:
        notes.append("官方轨迹暂无已打包待揽收事件")
    notes.append("轨迹由ERP翻译，地名及未匹配描述保留原文；飞书自动同步不生成Excel导出时间")
    values = [
        order["shopName"], str(order["orderNumber"]), LABELS.get(live.get("platformStatus") or order["platformStatus"],
                                                               live.get("platformStatus") or order["platformStatus"]),
        LABELS.get(tracking, tracking) if tracking else ("官方暂无轨迹" if live else "等待后台查询"),
        display_time(created, timezone), display_time(packed.get("occurredAt"), timezone),
        display_time(live.get("firstLocationAt"), timezone), display_time(live.get("deliveredAt"), timezone),
        hours(created, packed.get("occurredAt")), hours(created, live.get("firstLocationAt")),
        days(created, live.get("deliveredAt")),
        translate(live.get("firstLocationDescription")),
        translate(latest.get("description")) or LABELS.get(latest.get("status"), latest.get("status", "")),
        translate(packed.get("description")), translate(live.get("deliveredDescription")),
        display_time(live.get("checkedAt")), display_time(order.get("erpSyncedAt")),
        "\n".join(p["packageId"] for p in packages),
        "\n".join(LABELS.get(p["packageStatus"], p["packageStatus"]) for p in packages),
        "\n".join(p.get("carrierName") or "承运商未知" for p in packages),
        "\n".join(p.get("trackingNumberMasked") or "" for p in packages), "；".join(notes), "",
        shipping_method(shipping, fulfillment),
    ]
    row = dict(zip(EXCEL_FIELDS, values, strict=True))
    upcoming = [NODE_NAMES[k] for k, seconds in flags.items() if seconds < 0]
    overdue = [NODE_NAMES[k] for k, seconds in flags.items() if seconds >= 0]
    details = []
    for key, seconds in flags.items():
        minutes = int(abs(seconds)) // 60
        details.append(f"{NODE_NAMES[key]}：{'剩余' if seconds < 0 else '已超时'}{minutes // 60}小时{minutes % 60}分钟")
    row.update({"ERP订单键": order["key"], "预警状态": RED if overdue else YELLOW if upcoming else RESOLVED,
                "预警节点": [NODE_NAMES[k] for k in flags], "快超时节点": "、".join(upcoming),
                "已超时节点": "、".join(overdue), "节点预警详情": "\n".join(details),
                "最近飞书同步时间": display_time(now)})
    return row
