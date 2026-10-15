from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class DetectionSnapshot:
    waybill_id: object
    waybill_status: str
    tracking_status: str | None
    waybill_updated_at: datetime
    tracking_occurred_at: datetime | None
    task_status: str
    order_status: str | None
    order_external_status: str | None
    event_id: object | None
    event_raw_status: str | None
    event_description: str | None


@dataclass(frozen=True)
class ExceptionCandidate:
    exception_type: str
    severity: str
    source: str
    title: str
    description: str
    source_event_id: object | None = None


EVENT_RULES = (
    (
        "address_error",
        "high",
        "地址错误",
        (
            "ADDRESS ERROR",
            "INCORRECT ADDRESS",
            "BAD ADDRESS",
            "WRONG ADDRESS",
            "地址错误",
            "地址不详",
        ),
    ),
    ("refused", "high", "客户拒收", ("REFUSED", "REJECTED BY RECIPIENT", "拒收")),
    (
        "lost",
        "critical",
        "包裹丢失",
        ("LOST", "MISSING PARCEL", "PARCEL MISSING", "丢失", "遗失"),
    ),
    ("damaged", "high", "包裹破损", ("DAMAGED", "DAMAGE", "BROKEN", "破损", "损坏")),
)


def detect_exception_candidates(
    snapshot: DetectionSnapshot,
    *,
    now: datetime,
    pickup_timeout: timedelta,
    stalled_timeout: timedelta,
    platform_grace: timedelta,
) -> list[ExceptionCandidate]:
    candidates = _event_candidates(snapshot)
    if (
        snapshot.waybill_status == "shipped"
        and snapshot.tracking_status in {None, "info_received"}
        and snapshot.waybill_updated_at <= now - pickup_timeout
    ):
        candidates.append(
            ExceptionCandidate(
                "not_picked_up",
                "medium",
                "scheduled_scan",
                "超时未揽收",
                f"发货后超过 {int(pickup_timeout.total_seconds() // 3600)} 小时仍未揽收。",
            )
        )
    last_movement = snapshot.tracking_occurred_at or snapshot.waybill_updated_at
    if (
        snapshot.tracking_status in {"picked_up", "in_transit", "out_for_delivery"}
        and last_movement <= now - stalled_timeout
    ):
        candidates.append(
            ExceptionCandidate(
                "stalled",
                "medium",
                "scheduled_scan",
                "运输滞留",
                f"超过 {int(stalled_timeout.total_seconds() // 3600)} 小时没有新的有效轨迹。",
            )
        )
    if (
        snapshot.waybill_updated_at <= now - platform_grace
        and _platform_status_mismatch(
            snapshot.waybill_status,
            snapshot.task_status,
            snapshot.order_status,
        )
    ):
        candidates.append(
            ExceptionCandidate(
                "platform_status_mismatch",
                "high",
                "scheduled_scan",
                "平台状态不一致",
                "ERP 物流状态与平台订单状态不一致："
                f"{snapshot.task_status} / {snapshot.order_external_status or snapshot.order_status or 'unknown'}。",
            )
        )
    return candidates


def _event_candidates(snapshot: DetectionSnapshot) -> list[ExceptionCandidate]:
    if snapshot.event_id is None:
        return []
    text = " ".join(
        part for part in (snapshot.event_raw_status, snapshot.event_description) if part
    ).upper()
    return [
        ExceptionCandidate(
            exception_type,
            severity,
            "tracking_event",
            title,
            snapshot.event_description or snapshot.event_raw_status or title,
            snapshot.event_id,
        )
        for exception_type, severity, title, keywords in EVENT_RULES
        if any(keyword in text for keyword in keywords)
    ]


def _platform_status_mismatch(
    waybill_status: str, task_status: str, order_status: str | None
) -> bool:
    if not order_status:
        return False
    if waybill_status == "cancelled":
        return order_status != "cancelled"
    if waybill_status == "delivered":
        return order_status not in {"delivered", "completed"}
    if task_status == "delivered":
        return order_status not in {"delivered", "completed"}
    if task_status in {"shipped", "in_transit"}:
        return order_status not in {
            "partially_shipped",
            "in_transit",
            "delivered",
            "completed",
        }
    return order_status in {"delivered", "completed"} and task_status not in {
        "delivered",
        "cancelled",
    }
