import hashlib
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.carrier_tracking_adapter import CarrierTrackingUpdate
from erp_api.services.logistics_tracking_status import is_tracking_regression


def tracking_dedupe_key(update: CarrierTrackingUpdate) -> str:
    identity = update.external_event_id or "|".join(
        (
            update.raw_status,
            update.occurred_at.isoformat(),
            str(update.sequence_no or ""),
            update.location or "",
            update.description or "",
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def tracking_ignored_reason(waybill, update, normalized):
    if normalized is None:
        return "unknown_status"
    if waybill.status not in {"shipped", "in_transit", "exception", "delivered"}:
        return "erp_not_dispatched"
    if (
        waybill.tracking_sequence is not None
        and update.sequence_no is not None
        and update.sequence_no <= waybill.tracking_sequence
    ):
        return "out_of_order_sequence"
    if (
        waybill.tracking_occurred_at
        and update.occurred_at < waybill.tracking_occurred_at
    ):
        return "out_of_order_time"
    same_timestamp = waybill.tracking_occurred_at == update.occurred_at
    if is_tracking_regression(
        waybill.tracking_status, normalized, same_timestamp=same_timestamp
    ):
        return "status_regression"
    return None


async def apply_waybill_tracking_status(session, waybill, normalized, update):
    waybill.tracking_status = normalized
    waybill.tracking_occurred_at = update.occurred_at
    if update.sequence_no is not None:
        waybill.tracking_sequence = update.sequence_no
    package = await session.get(LogisticsPackage, waybill.package_id)
    if package is None:
        return
    task = await session.get(LogisticsTask, package.task_id, with_for_update=True)
    if task is None:
        return
    if normalized in {"picked_up", "in_transit", "out_for_delivery"}:
        waybill.status = "in_transit"
        if task.status not in {"delivered", "cancelled"}:
            task.status = "in_transit"
    elif normalized == "delivered":
        waybill.status = "delivered"
        await session.flush()
        pending = await session.scalar(
            select(LogisticsPackage.id)
            .outerjoin(
                LogisticsWaybill,
                and_(
                    LogisticsWaybill.package_id == LogisticsPackage.id,
                    LogisticsWaybill.is_current.is_(True),
                ),
            )
            .where(
                LogisticsPackage.task_id == task.id,
                LogisticsPackage.status != "cancelled",
                or_(
                    LogisticsWaybill.id.is_(None),
                    LogisticsWaybill.status != "delivered",
                ),
            )
            .limit(1)
        )
        task.status = "delivered" if pending is None else "in_transit"
    elif normalized in {"exception", "returned", "cancelled"}:
        waybill.status = "exception"
        task.status = "exception"
    task.updated_at = datetime.now(UTC)


def tracking_event_record(event):
    return {
        "id": event.id,
        "waybillId": event.waybill_id,
        "source": event.source,
        "externalEventId": event.external_event_id,
        "rawStatus": event.raw_status,
        "status": event.normalized_status,
        "sequence": event.sequence_no,
        "occurredAt": event.occurred_at,
        "receivedAt": event.received_at,
        "location": event.location,
        "description": event.description,
        "accepted": event.accepted,
        "ignoredReason": event.ignored_reason,
    }
