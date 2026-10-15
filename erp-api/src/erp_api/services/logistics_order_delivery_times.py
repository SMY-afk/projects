from sqlalchemy import func, select

from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_tracking_event import LogisticsTrackingEvent
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.services.tiktok_tracking_event_status import tracking_status


async def delivered_times(session, tenant, order_ids):
    if not order_ids:
        return {}
    packages = (
        await session.execute(
            select(OrderFulfillment.order_id, func.min(OrderFulfillment.delivered_at))
            .where(
                OrderFulfillment.tenant_id == tenant,
                OrderFulfillment.order_id.in_(order_ids),
            )
            .group_by(OrderFulfillment.order_id)
        )
    ).all()
    result = {order: occurred for order, occurred in packages if occurred}
    events = (
        await session.execute(
            select(
                LogisticsTask.order_id,
                LogisticsTrackingEvent.occurred_at,
                LogisticsTrackingEvent.external_event_id,
                LogisticsTrackingEvent.description,
            )
            .join(LogisticsPackage, LogisticsPackage.task_id == LogisticsTask.id)
            .join(LogisticsWaybill, LogisticsWaybill.package_id == LogisticsPackage.id)
            .join(
                LogisticsTrackingEvent,
                LogisticsTrackingEvent.waybill_id == LogisticsWaybill.id,
            )
            .where(
                LogisticsTask.tenant_id == tenant,
                LogisticsTask.order_id.in_(order_ids),
                LogisticsPackage.tenant_id == tenant,
                LogisticsWaybill.tenant_id == tenant,
                LogisticsWaybill.is_current.is_(True),
                LogisticsTrackingEvent.tenant_id == tenant,
                LogisticsTrackingEvent.accepted.is_(True),
                LogisticsTrackingEvent.normalized_status == "delivered",
                LogisticsTrackingEvent.external_event_id.like("tiktok:%"),
            )
        )
    ).all()
    verified = {}
    for order, occurred, event_id, description in events:
        code = (event_id or "").split(":")[2]
        if tracking_status(code, description) == "delivered":
            verified[order] = min(verified.get(order, occurred), occurred)
    result.update(verified)
    return result
