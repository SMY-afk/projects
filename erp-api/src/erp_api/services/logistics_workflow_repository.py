from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.logistics_task_review import LogisticsTaskReview
from erp_api.services.logistics_records import task_record
from erp_api.services.logistics_repository import (
    LogisticsTaskConflictError,
    LogisticsTaskValidationError,
)


@dataclass(frozen=True)
class ReviewItemInput:
    task_item_id: UUID
    actual_quantity: int
    difference_reason: str | None


class LogisticsWorkflowRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def confirm_picking_completed(
        self,
        tenant_id: UUID,
        task_id: UUID,
        *,
        actor_user_id: UUID,
        note: str | None,
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            task = await _load_task(session, task_id)
            if task is None:
                return None
            if task.status != "pending_review":
                raise LogisticsTaskConflictError(
                    "Only a task pending review can complete picking."
                )
            if _picking_completed(task):
                raise LogisticsTaskConflictError("Picking was already completed.")
            task.operations.append(
                LogisticsTaskOperation(
                    tenant_id=tenant_id,
                    operation_type="picking_completed",
                    from_status=task.status,
                    to_status=task.status,
                    actor_user_id=actor_user_id,
                    note=note,
                    details={"method": "manual"},
                )
            )
            task.updated_at = datetime.now(UTC)
            await _commit(session, "The logistics task was changed.")
            return task_record(task)
        return None

    async def resolve_scan(
        self,
        tenant_id: UUID,
        *,
        code: str,
        task_id: UUID | None,
    ) -> dict[str, object]:
        normalized = code.strip()
        async for session in self._database.session(tenant_id):
            task_matches = await session.scalars(
                select(LogisticsTask)
                .where(
                    LogisticsTask.status != "cancelled",
                    or_(
                        LogisticsTask.task_number == normalized,
                        LogisticsTask.source_number == normalized,
                    ),
                    *([LogisticsTask.id == task_id] if task_id else []),
                )
                .order_by(LogisticsTask.created_at, LogisticsTask.id)
            )
            tasks = task_matches.all()
            if tasks:
                return {
                    "code": normalized,
                    "matchType": "task",
                    "tasks": [_scan_task(item) for item in tasks],
                    "items": [],
                }
            item_matches = await session.execute(
                select(LogisticsTaskItem, LogisticsTask)
                .join(LogisticsTask, LogisticsTask.id == LogisticsTaskItem.task_id)
                .where(
                    LogisticsTask.status != "cancelled",
                    or_(
                        LogisticsTaskItem.seller_sku == normalized,
                        LogisticsTaskItem.platform_sku_id == normalized,
                    ),
                    *([LogisticsTask.id == task_id] if task_id else []),
                )
                .order_by(LogisticsTask.created_at, LogisticsTaskItem.id)
            )
            items = item_matches.all()
            if not items:
                return {
                    "code": normalized,
                    "matchType": "none",
                    "tasks": [],
                    "items": [],
                }
            return {
                "code": normalized,
                "matchType": "task_item",
                "tasks": [],
                "items": [_scan_item(item, task) for item, task in items],
            }
        raise RuntimeError("Tenant database session was not created.")

    async def record_review(
        self,
        tenant_id: UUID,
        task_id: UUID,
        *,
        actor_user_id: UUID,
        items: list[ReviewItemInput],
        note: str | None,
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            task = await _load_task(session, task_id)
            if task is None:
                return None
            if task.status != "pending_review":
                raise LogisticsTaskConflictError(
                    "Only a task pending review can be reviewed."
                )
            if not _picking_completed(task):
                raise LogisticsTaskConflictError(
                    "Picking must be confirmed before review."
                )
            review_items = {item.task_item_id: item for item in items}
            task_items = {item.id: item for item in task.items}
            if (
                len(review_items) != len(items)
                or review_items.keys() != task_items.keys()
            ):
                raise LogisticsTaskValidationError(
                    "Review quantities must include every task item exactly once."
                )
            differences = _differences(task_items, review_items)
            expected_quantity = sum(item.planned_quantity for item in task.items)
            actual_quantity = sum(item.actual_quantity for item in items)
            result = _review_result(differences)
            task.status = "pending_pack" if result == "passed" else "exception"
            task.reviews.append(
                LogisticsTaskReview(
                    tenant_id=tenant_id,
                    result=result,
                    expected_quantity=expected_quantity,
                    actual_quantity=actual_quantity,
                    differences=differences,
                    note=note,
                    reviewer_user_id=actor_user_id,
                )
            )
            task.operations.append(
                LogisticsTaskOperation(
                    tenant_id=tenant_id,
                    operation_type="reviewed",
                    from_status="pending_review",
                    to_status=task.status,
                    actor_user_id=actor_user_id,
                    note=note,
                    details={"result": result},
                )
            )
            task.updated_at = datetime.now(UTC)
            await _commit(session, "The logistics task was changed during review.")
            return task_record(task)
        return None


def _differences(task_items, review_items) -> list[dict[str, object]]:
    differences = []
    for item_id, task_item in task_items.items():
        review_item = review_items[item_id]
        is_different = review_item.actual_quantity != task_item.planned_quantity
        if is_different and review_item.difference_reason is None:
            raise LogisticsTaskValidationError(
                "A difference reason is required when quantity does not match."
            )
        if not is_different and review_item.difference_reason is not None:
            raise LogisticsTaskValidationError(
                "A difference reason is only allowed when quantity does not match."
            )
        if is_different:
            differences.append(
                {
                    "taskItemId": str(item_id),
                    "sellerSku": task_item.seller_sku,
                    "expectedQuantity": task_item.planned_quantity,
                    "actualQuantity": review_item.actual_quantity,
                    "differenceQuantity": (
                        review_item.actual_quantity - task_item.planned_quantity
                    ),
                    "reason": review_item.difference_reason,
                }
            )
    return differences


def _review_result(differences: list[dict[str, object]]) -> str:
    if not differences:
        return "passed"
    if any(item["reason"] == "damaged" for item in differences):
        return "damaged"
    return "quantity_mismatch"


def _picking_completed(task: LogisticsTask) -> bool:
    return any(item.operation_type == "picking_completed" for item in task.operations)


def _scan_task(task: LogisticsTask) -> dict[str, object]:
    return {
        "taskId": task.id,
        "taskNumber": task.task_number,
        "sourceNumber": task.source_number,
        "status": task.status,
    }


def _scan_item(item: LogisticsTaskItem, task: LogisticsTask) -> dict[str, object]:
    return {
        **_scan_task(task),
        "taskItemId": item.id,
        "sellerSku": item.seller_sku,
        "platformSkuId": item.platform_sku_id,
        "productName": item.product_name,
        "skuName": item.sku_name,
        "plannedQuantity": item.planned_quantity,
    }


async def _load_task(session, task_id: UUID) -> LogisticsTask | None:
    return await session.scalar(
        select(LogisticsTask)
        .options(
            selectinload(LogisticsTask.items),
            selectinload(LogisticsTask.operations),
            selectinload(LogisticsTask.reviews),
        )
        .where(LogisticsTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _commit(session, message: str) -> None:
    try:
        await session.commit()
    except StaleDataError as error:
        raise LogisticsTaskConflictError(message) from error
