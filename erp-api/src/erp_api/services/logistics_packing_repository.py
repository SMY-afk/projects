from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_package import LogisticsPackage, LogisticsPackageItem
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.logistics_packing_helpers import (
    commit_packing,
    load_package,
    load_package_for_update,
    load_task,
    new_package_number,
    operation,
    packing_status,
    require_draft,
    require_packable_task,
    validate_unique_items,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_shipping_records import package_record


@dataclass(frozen=True)
class PackageItemInput:
    task_item_id: UUID
    quantity: int


class LogisticsPackingRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_draft(
        self,
        tenant_id: UUID,
        task_id: UUID,
        *,
        actor_user_id: UUID,
        note: str | None,
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            task = await load_task(session, task_id)
            if task is None:
                return None
            require_packable_task(task)
            package = LogisticsPackage(
                id=uuid4(),
                tenant_id=tenant_id,
                task_id=task_id,
                package_number=new_package_number(),
                status="draft",
                note=note,
                created_by_user_id=actor_user_id,
            )
            task.updated_at = datetime.now(UTC)
            session.add_all(
                [
                    package,
                    operation(
                        tenant_id,
                        task,
                        actor_user_id,
                        "package_draft_created",
                        package,
                    ),
                ]
            )
            await commit_packing(session)
            return package_record(await load_package(session, package.id))
        return None

    async def update_draft(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        version_id: int,
        items: list[PackageItemInput],
        weight_grams: int | None,
        length_mm: int | None,
        width_mm: int | None,
        height_mm: int | None,
        note: str | None,
    ) -> dict[str, object] | None:
        validate_unique_items(items)
        async for session in self._database.session(tenant_id):
            package = await load_package_for_update(session, package_id)
            if package is None:
                return None
            require_draft(package, version_id)
            task = await load_task(session, package.task_id)
            if task is None:
                return None
            require_packable_task(task)
            task_items = {item.id: item for item in task.items}
            for item in items:
                task_item = task_items.get(item.task_item_id)
                if task_item is None:
                    raise LogisticsShippingValidationError(
                        "A package item does not belong to the logistics task."
                    )
                if (
                    item.quantity
                    > task_item.planned_quantity - task_item.packed_quantity
                ):
                    raise LogisticsShippingConflictError(
                        "Draft quantity exceeds the task item's unpacked quantity."
                    )
            package.items.clear()
            await session.flush()
            package.items.extend(
                LogisticsPackageItem(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    task_item_id=item.task_item_id,
                    quantity=item.quantity,
                )
                for item in items
            )
            package.weight_grams = weight_grams
            package.length_mm = length_mm
            package.width_mm = width_mm
            package.height_mm = height_mm
            package.note = note
            package.updated_at = datetime.now(UTC)
            task.updated_at = datetime.now(UTC)
            session.add(
                operation(
                    tenant_id,
                    task,
                    actor_user_id,
                    "package_draft_updated",
                    package,
                )
            )
            await commit_packing(session)
            return package_record(await load_package(session, package.id))
        return None

    async def seal(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        version_id: int,
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            package = await load_package_for_update(session, package_id)
            if package is None:
                return None
            require_draft(package, version_id)
            if not package.items or None in (
                package.weight_grams,
                package.length_mm,
                package.width_mm,
                package.height_mm,
            ):
                raise LogisticsShippingValidationError(
                    "Package items, weight, and all dimensions are required before sealing."
                )
            task = await load_task(session, package.task_id)
            if task is None:
                return None
            require_packable_task(task)
            task_items = {item.id: item for item in task.items}
            for item in package.items:
                task_item = task_items[item.task_item_id]
                if (
                    item.quantity
                    > task_item.planned_quantity - task_item.packed_quantity
                ):
                    raise LogisticsShippingConflictError(
                        "Package quantity exceeds the task item's unpacked quantity."
                    )
                task_item.packed_quantity += item.quantity
            previous_status = task.status
            task.status = packing_status(task)
            task.updated_at = datetime.now(UTC)
            package.status = "packed"
            package.sealed_by_user_id = actor_user_id
            package.sealed_at = datetime.now(UTC)
            package.updated_at = datetime.now(UTC)
            session.add(
                operation(
                    tenant_id,
                    task,
                    actor_user_id,
                    "package_sealed",
                    package,
                    from_status=previous_status,
                )
            )
            await commit_packing(session)
            return package_record(await load_package(session, package.id))
        return None

    async def unseal(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        version_id: int,
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            package = await load_package_for_update(session, package_id)
            if package is None:
                return None
            if package.version_id != version_id:
                raise LogisticsShippingConflictError("The package version is stale.")
            if package.status != "packed":
                raise LogisticsShippingConflictError(
                    "Only a sealed package without a waybill can be unsealed."
                )
            has_waybill = await session.scalar(
                select(LogisticsWaybill.id).where(
                    LogisticsWaybill.package_id == package.id,
                    LogisticsWaybill.is_current.is_(True),
                )
            )
            if has_waybill is not None:
                raise LogisticsShippingConflictError(
                    "A package with a waybill cannot be unsealed."
                )
            task = await load_task(session, package.task_id)
            if task is None:
                return None
            previous_status = task.status
            task_items = {item.id: item for item in task.items}
            for item in package.items:
                task_item = task_items[item.task_item_id]
                task_item.packed_quantity -= item.quantity
            task.status = "pending_pack"
            task.updated_at = datetime.now(UTC)
            package.status = "draft"
            package.sealed_by_user_id = None
            package.sealed_at = None
            package.updated_at = datetime.now(UTC)
            session.add(
                operation(
                    tenant_id,
                    task,
                    actor_user_id,
                    "package_unsealed",
                    package,
                    from_status=previous_status,
                )
            )
            await commit_packing(session)
            return package_record(await load_package(session, package.id))
        return None
