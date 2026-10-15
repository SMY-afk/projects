from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_document import LogisticsDocument
from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order import Order
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.platform_fulfillment_outbox import PlatformFulfillmentOutbox
from erp_api.models.shop import Shop
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_shipping_records import package_record, waybill_record


class LogisticsDispatchRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def dispatch(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        package_version_id: int,
        waybill_id: UUID,
        waybill_version_id: int,
        actual_quantities: list[tuple[UUID, int]],
        actor_user_id: UUID,
        note: str | None,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            package = await session.scalar(
                select(LogisticsPackage)
                .options(selectinload(LogisticsPackage.items))
                .where(LogisticsPackage.id == package_id)
                .with_for_update()
            )
            if package is None:
                raise LogisticsShippingNotFoundError("Package was not found.")
            waybill = await session.get(
                LogisticsWaybill, waybill_id, with_for_update=True
            )
            _validate_aggregate_versions(
                package,
                waybill,
                package_version_id=package_version_id,
                waybill_version_id=waybill_version_id,
            )
            await _require_current_label(session, waybill_id)
            shipped_items = await _apply_actual_quantities(
                session, package, actual_quantities
            )
            task = await session.get(
                LogisticsTask, package.task_id, with_for_update=True
            )
            if task is None:
                raise LogisticsShippingNotFoundError("Logistics task was not found.")
            previous_status = task.status
            package.status = "shipped"
            waybill.status = "shipped"
            waybill.tracking_next_poll_at = datetime.now(UTC)
            task.updated_at = datetime.now(UTC)
            await session.flush()
            statuses = await session.scalars(
                select(LogisticsPackage.status).where(
                    LogisticsPackage.task_id == task.id,
                    LogisticsPackage.status != "cancelled",
                )
            )
            task.status = (
                "shipped"
                if all(value == "shipped" for value in statuses.all())
                else "pending_dispatch"
            )
            callback_id = await _create_platform_callback(
                session, tenant_id, task, package, waybill
            )
            session.add(
                LogisticsTaskOperation(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    operation_type="package_dispatched",
                    from_status=previous_status,
                    to_status=task.status,
                    actor_user_id=actor_user_id,
                    note=note,
                    details={
                        "packageId": str(package.id),
                        "waybillId": str(waybill.id),
                        "actualQuantities": shipped_items,
                        "platformCallbackId": str(callback_id) if callback_id else None,
                    },
                )
            )
            try:
                await session.commit()
            except StaleDataError as error:
                raise LogisticsShippingConflictError(
                    "Dispatch data was changed by another operation."
                ) from error
            package = await session.scalar(
                select(LogisticsPackage)
                .options(selectinload(LogisticsPackage.items))
                .where(LogisticsPackage.id == package_id)
                .execution_options(populate_existing=True)
            )
            await session.refresh(waybill)
            await session.refresh(task)
            if package is None:
                raise LogisticsShippingNotFoundError("Package was not found.")
            return {
                "package": package_record(package),
                "waybill": waybill_record(waybill),
                "taskId": task.id,
                "taskStatus": task.status,
                "taskVersionId": task.version_id,
                "shippedItems": shipped_items,
                "platformCallbackId": callback_id,
            }
        raise RuntimeError("Tenant database session was not created.")


def _validate_aggregate_versions(
    package, waybill, *, package_version_id, waybill_version_id
):
    if package.version_id != package_version_id:
        raise LogisticsShippingConflictError("The package has changed.")
    if package.status != "waybill_created":
        raise LogisticsShippingConflictError("Package is not ready for dispatch.")
    if waybill is None or waybill.package_id != package.id:
        raise LogisticsShippingNotFoundError("Current package waybill was not found.")
    if waybill.version_id != waybill_version_id:
        raise LogisticsShippingConflictError("The waybill has changed.")
    if not waybill.is_current or waybill.status not in {"created", "label_ready"}:
        raise LogisticsShippingConflictError("Waybill is not ready for dispatch.")


async def _require_current_label(session, waybill_id: UUID) -> None:
    label_id = await session.scalar(
        select(LogisticsDocument.id).where(
            LogisticsDocument.document_type == "shipping_label",
            LogisticsDocument.owner_reference_id == waybill_id,
            LogisticsDocument.is_current.is_(True),
        )
    )
    if label_id is None:
        raise LogisticsShippingValidationError(
            "A persisted shipping label is required before dispatch."
        )


async def _apply_actual_quantities(session, package, actual_quantities):
    provided = dict(actual_quantities)
    if len(provided) != len(actual_quantities):
        raise LogisticsShippingValidationError("Duplicate dispatch item was provided.")
    expected = {item.task_item_id: item.quantity for item in package.items}
    if provided != expected:
        raise LogisticsShippingValidationError(
            "Actual shipped quantities must match the sealed package quantities."
        )
    task_items = await session.scalars(
        select(LogisticsTaskItem)
        .where(LogisticsTaskItem.id.in_(provided))
        .with_for_update()
    )
    records = {item.id: item for item in task_items.all()}
    if records.keys() != provided.keys():
        raise LogisticsShippingValidationError(
            "Dispatch item does not belong to the task."
        )
    result: list[dict[str, object]] = []
    for item_id, quantity in provided.items():
        item = records[item_id]
        if (
            item.task_id != package.task_id
            or item.shipped_quantity + quantity > item.packed_quantity
        ):
            raise LogisticsShippingValidationError(
                "Actual shipped quantity exceeds the packed quantity."
            )
        item.shipped_quantity += quantity
        result.append({"taskItemId": str(item_id), "quantity": quantity})
    return result


async def _create_platform_callback(session, tenant_id, task, package, waybill):
    if task.source_type != "sales_order" or task.order_id is None:
        return None
    order_context = (
        await session.execute(
            select(Order.platform_order_id, Order.shop_id, Shop.platform)
            .join(Shop, Shop.id == Order.shop_id)
            .where(Order.id == task.order_id)
        )
    ).one_or_none()
    if order_context is None:
        raise LogisticsShippingNotFoundError(
            "Sales order platform context was not found."
        )
    active_packages = (
        await session.scalars(
            select(LogisticsPackage.id).where(
                LogisticsPackage.task_id == task.id,
                LogisticsPackage.status != "cancelled",
            )
        )
    ).all()
    platform_packages = (
        await session.scalars(
            select(OrderFulfillment.platform_package_id).where(
                OrderFulfillment.order_id == task.order_id
            )
        )
    ).all()
    platform_package_id = (
        platform_packages[0]
        if len(active_packages) == 1 and len(platform_packages) == 1
        else None
    )
    callback_id = uuid4()
    session.add(
        PlatformFulfillmentOutbox(
            id=callback_id,
            tenant_id=tenant_id,
            task_id=task.id,
            package_id=package.id,
            waybill_id=waybill.id,
            order_id=task.order_id,
            shop_id=order_context.shop_id,
            platform=order_context.platform,
            event_type="shipment_confirmed",
            platform_order_id=order_context.platform_order_id,
            platform_package_id=platform_package_id,
            idempotency_key=f"shipment_confirmed:{package.id}",
            status="pending",
            attempt_count=0,
        )
    )
    return callback_id
