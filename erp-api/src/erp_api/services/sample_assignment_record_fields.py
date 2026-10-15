from __future__ import annotations

from datetime import datetime
from uuid import UUID

from erp_api.services.sample_application_identity import display_application_id

ASSIGNMENT_RECORD_SCHEMA = (
    ("分配编号", 1),
    ("申请编号", 1),
    ("达人ID", 1),
    ("店铺名称", 1),
    ("样品编号", 1),
    ("分配BD", 1),
    ("分配提醒", 1),
    ("分配人", 1),
    ("分配时间", 5),
    ("通知状态", 1),
    ("通知时间", 5),
    ("备注", 1),
)
ASSIGNMENT_RECORD_FIELDS = frozenset(name for name, _ in ASSIGNMENT_RECORD_SCHEMA)
NOTIFICATION_STATUS_LABELS = {
    "pending": "待通知",
    "processing": "通知中",
    "sent": "已通知",
    "retry_wait": "待重试",
    "failed": "通知失败",
    "cancelled": "已取消",
}
CANCELLED_NOTIFICATION_STATUSES = frozenset({"cancelled", "已取消"})
SHOP_DISPLAY_SUFFIX_BY_ID = {
    UUID("eb7678c2-67d6-5446-85f0-dc8fba9b75d6"): "跨境3",
    UUID("50770999-40ce-5b84-bb01-13701932bdf1"): "跨境4",
    UUID("fe629cb8-fa7b-56a5-970c-2f6e9ebc5703"): "跨境7",
    UUID("5e1fed24-8268-5b5a-9ead-5efb862e7a51"): "跨境12",
    UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10"): "本土店",
}


def record_fields(row) -> dict[str, object]:
    outbox, application, workflow, shop = row
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    assigned_bd = payload.get("assigned_bd_name") or workflow.assigned_bd_name
    source_event = payload.get("source_event_id")
    if not isinstance(assigned_bd, str) or not assigned_bd:
        raise ValueError("Assignment record is missing its BD name.")
    if not isinstance(source_event, str) or not source_event.startswith("bd-auto:"):
        raise ValueError("Assignment record is missing its source event.")
    application_id = display_application_id(
        application.platform_application_id,
        raw_payload=application.raw_payload,
    )
    if not application_id:
        raise ValueError("Assignment record is missing its TikTok application ID.")
    fields: dict[str, object] = {
        "分配编号": str(outbox.id),
        "申请编号": application_id,
        "达人ID": application.creator_username or "",
        "样品编号": application.sku_id or application.product_id or "-",
        "分配BD": assigned_bd,
        "分配提醒": assignment_notice(payload.get("assignment_notice")),
        "分配人": "ERP自动分配",
        "分配时间": timestamp_ms(workflow.assigned_at or outbox.created_at),
        "通知状态": NOTIFICATION_STATUS_LABELS[outbox.status],
        "备注": f"current-application:{source_event}",
        "店铺名称": assignment_shop_name(shop),
    }
    if outbox.sent_at is not None:
        fields["通知时间"] = timestamp_ms(outbox.sent_at)
    if getattr(application, "sample_type", "free") == "refundable":
        fields["达人ID"] = "@" + (application.creator_username or "").strip().lstrip("@")
    return fields


def assignment_notice(value: object) -> str:
    if value == "same_creator_level_rotation_conflict":
        return "同达人原BD与本店本等级轮转冲突，已改分当前BD"
    if value == "same_creator_level_imbalance":
        return "同达人原BD的本店本等级数量偏高，已均衡改分"
    return ""


def is_cancelled_assignment_record(fields: dict[str, object]) -> bool:
    value = fields.get("通知状态")
    return (
        isinstance(value, str)
        and value.strip().casefold() in CANCELLED_NOTIFICATION_STATUSES
    )


def assignment_shop_name(shop) -> str:
    shop_name = shop.shop_name
    suffix = SHOP_DISPLAY_SUFFIX_BY_ID.get(getattr(shop, "id", None))
    return f"{shop_name}（{suffix}）" if suffix else shop_name


def creator_record_key(fields: dict[str, object]) -> tuple[str, str]:
    shop = fields.get("店铺名称")
    creator = fields.get("达人ID")
    return (
        base_shop_name(shop).casefold() if isinstance(shop, str) else "",
        creator.strip().lstrip("@").casefold() if isinstance(creator, str) else "",
    )


def base_shop_name(value: str) -> str:
    normalized = value.strip()
    for suffix in SHOP_DISPLAY_SUFFIX_BY_ID.values():
        for formatted in (f"（{suffix}）", f"({suffix})"):
            if normalized.endswith(formatted):
                return normalized[: -len(formatted)].rstrip()
    return normalized


def timestamp_ms(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("Assignment record timestamp must include a timezone.")
    return int(value.timestamp() * 1000)
