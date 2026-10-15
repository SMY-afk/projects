from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingValidationError,
)


def validate_unique_items(items) -> None:
    if len({item.task_item_id for item in items}) != len(items):
        raise LogisticsShippingValidationError(
            "A task item can appear only once in a package."
        )


def require_draft(package: LogisticsPackage, version_id: int) -> None:
    if package.version_id != version_id:
        raise LogisticsShippingConflictError("The package version is stale.")
    if package.status != "draft":
        raise LogisticsShippingConflictError("Only a draft package can be edited.")


def require_packable_task(task: LogisticsTask) -> None:
    if task.status not in {"pending_pack", "pending_waybill"}:
        raise LogisticsShippingConflictError("Only a reviewed task can be packed.")


def packing_status(task: LogisticsTask) -> str:
    return (
        "pending_waybill"
        if sum(item.packed_quantity for item in task.items)
        == sum(item.planned_quantity for item in task.items)
        else "pending_pack"
    )


def operation(
    tenant_id,
    task,
    actor_user_id,
    operation_type,
    package,
    *,
    from_status=None,
):
    return LogisticsTaskOperation(
        tenant_id=tenant_id,
        task_id=task.id,
        operation_type=operation_type,
        from_status=from_status or task.status,
        to_status=task.status,
        actor_user_id=actor_user_id,
        details={"packageId": str(package.id), "packageNumber": package.package_number},
    )


async def load_task(session, task_id: UUID) -> LogisticsTask | None:
    return await session.scalar(
        select(LogisticsTask)
        .options(selectinload(LogisticsTask.items))
        .where(LogisticsTask.id == task_id)
        .with_for_update()
    )


def package_select():
    return select(LogisticsPackage).options(selectinload(LogisticsPackage.items))


async def load_package(session, package_id: UUID) -> LogisticsPackage:
    return await session.scalar(
        package_select()
        .where(LogisticsPackage.id == package_id)
        .execution_options(populate_existing=True)
    )


async def load_package_for_update(session, package_id: UUID):
    return await session.scalar(
        package_select().where(LogisticsPackage.id == package_id).with_for_update()
    )


async def commit_packing(session) -> None:
    try:
        await session.commit()
    except StaleDataError as error:
        raise LogisticsShippingConflictError(
            "The package was changed by another operation."
        ) from error


def new_package_number() -> str:
    return f"LP-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"
