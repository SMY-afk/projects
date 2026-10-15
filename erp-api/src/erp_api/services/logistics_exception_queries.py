from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from erp_api.models.logistics_carrier import LogisticsCarrier
from erp_api.models.logistics_exception import LogisticsException
from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_tracking_event import LogisticsTrackingEvent
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order import Order
from erp_api.services.logistics_exception_detection import DetectionSnapshot
from erp_api.services.logistics_exception_records import exception_record


@dataclass(frozen=True)
class DetectionContext:
    tenant_id: UUID
    waybill_id: UUID
    package_id: UUID
    task_id: UUID
    snapshot: DetectionSnapshot


def exception_record_query():
    return (
        select(LogisticsException, LogisticsTask, LogisticsCarrier, LogisticsWaybill)
        .join(
            LogisticsTask,
            and_(
                LogisticsTask.id == LogisticsException.task_id,
                LogisticsTask.tenant_id == LogisticsException.tenant_id,
            ),
        )
        .join(
            LogisticsWaybill,
            and_(
                LogisticsWaybill.id == LogisticsException.waybill_id,
                LogisticsWaybill.tenant_id == LogisticsException.tenant_id,
            ),
        )
        .join(
            LogisticsCarrier,
            and_(
                LogisticsCarrier.id == LogisticsWaybill.carrier_id,
                LogisticsCarrier.tenant_id == LogisticsWaybill.tenant_id,
            ),
        )
        .options(selectinload(LogisticsException.actions))
    )


def latest_event_subquery(event_id: UUID | None = None):
    query = select(
        LogisticsTrackingEvent.id.label("event_id"),
        LogisticsTrackingEvent.tenant_id.label("event_tenant_id"),
        LogisticsTrackingEvent.waybill_id,
        LogisticsTrackingEvent.raw_status,
        LogisticsTrackingEvent.description,
    ).where(LogisticsTrackingEvent.accepted.is_(True))
    if event_id:
        query = query.where(LogisticsTrackingEvent.id == event_id)
    return (
        query.distinct(LogisticsTrackingEvent.waybill_id)
        .order_by(
            LogisticsTrackingEvent.waybill_id,
            LogisticsTrackingEvent.occurred_at.desc(),
        )
        .subquery()
    )


def detection_query(latest):
    return (
        select(LogisticsWaybill, LogisticsPackage, LogisticsTask, Order, latest)
        .join(
            LogisticsPackage,
            and_(
                LogisticsPackage.id == LogisticsWaybill.package_id,
                LogisticsPackage.tenant_id == LogisticsWaybill.tenant_id,
            ),
        )
        .join(
            LogisticsTask,
            and_(
                LogisticsTask.id == LogisticsPackage.task_id,
                LogisticsTask.tenant_id == LogisticsPackage.tenant_id,
            ),
        )
        .outerjoin(
            Order,
            and_(
                Order.id == LogisticsTask.order_id,
                Order.tenant_id == LogisticsTask.tenant_id,
            ),
        )
        .outerjoin(
            latest,
            and_(
                latest.c.waybill_id == LogisticsWaybill.id,
                latest.c.event_tenant_id == LogisticsWaybill.tenant_id,
            ),
        )
    )


def to_detection_context(row) -> DetectionContext:
    waybill, package, task, order = row[:4]
    event_id, _, _, raw_status, description = row[4:]
    return DetectionContext(
        tenant_id=waybill.tenant_id,
        waybill_id=waybill.id,
        package_id=package.id,
        task_id=task.id,
        snapshot=DetectionSnapshot(
            waybill.id,
            waybill.status,
            waybill.tracking_status,
            waybill.updated_at,
            waybill.tracking_occurred_at,
            task.status,
            order.status if order else None,
            order.external_status if order else None,
            event_id,
            raw_status,
            description,
        ),
    )


def to_exception_record(row) -> dict[str, object]:
    return exception_record(row[0], row[1], row[2], row[3])


def exception_number(now: datetime) -> str:
    return f"LEX-{now:%Y%m%d}-{uuid4().hex[:10].upper()}"
