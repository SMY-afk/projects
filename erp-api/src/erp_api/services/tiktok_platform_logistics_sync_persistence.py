from __future__ import annotations

from datetime import UTC, datetime

from erp_api.models.logistics_package import LogisticsPackage, LogisticsPackageItem
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.services.tiktok_platform_logistics_sync_records import (
    mask_tracking,
    merge_waybill_status,
    package_number,
    package_status,
    task_number,
    task_status,
)


def create_task(tenant_id, order, actor_id) -> LogisticsTask:
    task = LogisticsTask(
        tenant_id=tenant_id,
        task_number=task_number(),
        source_type="sales_order",
        direction="forward",
        source_reference_id=order.id,
        source_number=order.order_number,
        order_id=order.id,
        shop_id=order.shop_id,
        priority="normal",
        status=task_status(order.external_status),
        note="Synced from TikTok platform fulfillment.",
        created_by_user_id=actor_id,
        items=[],
        operations=[],
        reviews=[],
        packages=[],
    )
    ensure_task_items(tenant_id, task, order)
    return task


def ensure_task_items(tenant_id, task, order) -> None:
    existing = {item.order_line_id for item in task.items}
    for line in order.lines:
        if line.id in existing:
            continue
        task.items.append(
            LogisticsTaskItem(
                tenant_id=tenant_id,
                source_line_id=line.id,
                order_line_id=line.id,
                platform_product_id=line.platform_product_id,
                platform_sku_id=line.platform_sku_id,
                seller_sku=line.seller_sku,
                product_name=line.product_name,
                sku_name=line.sku_name,
                planned_quantity=line.quantity,
            )
        )


def advance_task_items(task, order) -> None:
    quantities = {line.id: line.quantity for line in order.lines}
    for item in task.items:
        quantity = quantities.get(item.order_line_id, item.planned_quantity)
        item.planned_quantity = max(item.planned_quantity, quantity)
        item.packed_quantity = item.planned_quantity
        item.shipped_quantity = item.planned_quantity


def create_package(tenant_id, task, detail, actor_id):
    return LogisticsPackage(
        tenant_id=tenant_id,
        task_id=task.id,
        package_number=package_number(),
        status=package_status(detail.package_status),
        weight_grams=detail.weight_grams,
        length_mm=detail.length_mm,
        width_mm=detail.width_mm,
        height_mm=detail.height_mm,
        note="Synced from TikTok package detail.",
        created_by_user_id=actor_id,
        items=[],
        waybills=[],
    )


def assign_package_items(tenant_id, package, task, order, detail) -> None:
    line_ids = set(detail.order_line_item_ids)
    by_line = {line.id: line for line in order.lines}
    for item in task.items:
        line = by_line.get(item.order_line_id)
        if line is None or (line_ids and line.platform_line_id not in line_ids):
            continue
        package.items.append(
            LogisticsPackageItem(
                tenant_id=tenant_id,
                task_id=task.id,
                task_item_id=item.id,
                quantity=item.planned_quantity,
            )
        )


def update_package_and_waybill(
    package, waybill, carrier_id, order_status, detail, cipher
) -> None:
    package.status = package_status(detail.package_status)
    for field in ("weight_grams", "length_mm", "width_mm", "height_mm"):
        if getattr(detail, field) is not None:
            setattr(package, field, getattr(detail, field))
    waybill.carrier_id = carrier_id
    waybill.status = merge_waybill_status(
        waybill.status, detail.package_status, order_status
    )
    waybill.is_current = True
    waybill.tracking_number_masked = mask_tracking(detail.tracking_number)
    waybill.tracking_number_ciphertext = (
        cipher.encrypt(detail.tracking_number) if detail.tracking_number else None
    )
    waybill.tracking_number_hash = (
        cipher.fingerprint("tracking", detail.tracking_number)
        if detail.tracking_number
        else None
    )
    waybill.updated_at = detail.updated_at or datetime.now(UTC)


def update_order_fulfillment(order, detail, cipher) -> None:
    fulfillment = next(
        (
            item
            for item in order.fulfillments
            if item.platform_package_id == detail.package_id
        ),
        None,
    )
    if fulfillment is None:
        return
    fulfillment.status = detail.package_status[:64]
    fulfillment.delivery_option_id = detail.delivery_option_id
    fulfillment.carrier = detail.carrier_name
    fulfillment.tracking_number_masked = mask_tracking(detail.tracking_number)
    fulfillment.tracking_number_ciphertext = (
        cipher.encrypt(detail.tracking_number) if detail.tracking_number else None
    )
