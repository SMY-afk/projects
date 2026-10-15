from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_carrier import (
    LogisticsCarrier,
    LogisticsCarrierAccount,
    LogisticsCarrierService,
)
from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.carrier_adapter import WaybillResult
from erp_api.services.logistics_shipping_context import (
    ShippingContext,
    StoredWaybillContext,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_shipping_records import waybill_record
from erp_api.services.logistics_shipping_repository_helpers import (
    account_input,
    build_contexts,
    carrier_input,
    carrier_select,
    commit,
    destination_country,
    load_task,
    mask_tracking,
    operation,
    service_input,
)
from erp_api.services.token_cipher import TokenCipher


class LogisticsShippingRepository:
    def __init__(self, database: Database, tracking_cipher: TokenCipher | None) -> None:
        self._database = database
        self._tracking_cipher = tracking_cipher

    async def load_contexts(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        carrier_id: UUID | None,
        service_id: UUID | None,
        account_id: UUID | None,
    ) -> list[ShippingContext]:
        async for session in self._database.session(tenant_id):
            package = await session.get(LogisticsPackage, package_id)
            if package is None:
                raise LogisticsShippingNotFoundError("Package was not found.")
            if package.status not in {"packed", "waybill_created"}:
                raise LogisticsShippingConflictError(
                    "Only a sealed package can be quoted or shipped."
                )
            if not all(
                (
                    package.weight_grams,
                    package.length_mm,
                    package.width_mm,
                    package.height_mm,
                )
            ):
                raise LogisticsShippingValidationError(
                    "Package weight and dimensions are required."
                )
            destination = await destination_country(session, package.task_id)
            carriers = await session.scalars(
                carrier_select().where(
                    LogisticsCarrier.status == "active",
                    *(
                        (LogisticsCarrier.id == carrier_id,)
                        if carrier_id is not None
                        else ()
                    ),
                )
            )
            contexts = build_contexts(
                package,
                destination,
                carriers.unique().all(),
                service_id=service_id,
                account_id=account_id,
            )
            if not contexts:
                raise LogisticsShippingNotFoundError(
                    "No matching active carrier service was found."
                )
            return contexts
        return []

    async def persist_waybill(
        self,
        tenant_id: UUID,
        context: ShippingContext,
        result: WaybillResult,
        *,
        actor_user_id: UUID,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            package = await session.get(
                LogisticsPackage, context.parcel.package_id, with_for_update=True
            )
            if package is None:
                raise LogisticsShippingNotFoundError("Package was not found.")
            if package.status != "packed":
                raise LogisticsShippingConflictError(
                    "Only a sealed package without a waybill can create one."
                )
            current = await session.scalar(
                select(LogisticsWaybill.id).where(
                    LogisticsWaybill.package_id == package.id,
                    LogisticsWaybill.is_current.is_(True),
                )
            )
            if current is not None:
                raise LogisticsShippingConflictError(
                    "The package already has a current waybill."
                )
            waybill = LogisticsWaybill(
                tenant_id=tenant_id,
                package_id=package.id,
                carrier_id=context.carrier.id,
                service_id=context.service.id,
                account_id=context.account.id if context.account else None,
                waybill_number=f"WB-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}",
                external_waybill_id=result.external_waybill_id,
                tracking_number_masked=mask_tracking(result.tracking_number),
                tracking_number_ciphertext=self._encrypt(result.tracking_number),
                tracking_number_hash=(
                    self._tracking_cipher.fingerprint(
                        "tracking", result.tracking_number
                    )
                    if self._tracking_cipher and result.tracking_number
                    else None
                ),
                label_url=result.label_url,
                status="label_ready" if result.label_url else "created",
                is_current=True,
            )
            package.status = "waybill_created"
            task = await load_task(session, package.task_id)
            previous = task.status
            session.add(waybill)
            await session.flush()
            statuses = await session.scalars(
                select(LogisticsPackage.status).where(
                    LogisticsPackage.task_id == package.task_id,
                    LogisticsPackage.status != "cancelled",
                )
            )
            if all(value in {"waybill_created", "shipped"} for value in statuses):
                task.status = "pending_dispatch"
                task.updated_at = datetime.now(UTC)
            session.add(
                operation(
                    tenant_id,
                    task.id,
                    actor_user_id,
                    "waybill_created",
                    previous,
                    task.status,
                    {
                        "packageId": str(package.id),
                        "carrierId": str(context.carrier.id),
                    },
                )
            )
            await commit(session)
            await session.refresh(waybill)
            return waybill_record(waybill)
        raise RuntimeError("Tenant database session was not created.")

    async def load_waybill(
        self, tenant_id: UUID, waybill_id: UUID
    ) -> StoredWaybillContext:
        async for session in self._database.session(tenant_id):
            row = await session.execute(
                select(
                    LogisticsWaybill,
                    LogisticsCarrier,
                    LogisticsCarrierService,
                    LogisticsCarrierAccount,
                )
                .join(
                    LogisticsCarrier, LogisticsCarrier.id == LogisticsWaybill.carrier_id
                )
                .outerjoin(
                    LogisticsCarrierService,
                    LogisticsCarrierService.id == LogisticsWaybill.service_id,
                )
                .outerjoin(
                    LogisticsCarrierAccount,
                    LogisticsCarrierAccount.id == LogisticsWaybill.account_id,
                )
                .where(LogisticsWaybill.id == waybill_id)
            )
            result = row.one_or_none()
            if result is None:
                raise LogisticsShippingNotFoundError("Waybill was not found.")
            waybill, carrier, service, account = result
            return StoredWaybillContext(
                waybill.id,
                carrier_input(carrier),
                service_input(service),
                account_input(account),
                waybill.external_waybill_id,
                waybill.label_url,
                waybill.version_id,
                waybill.status,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def cancel_waybill(
        self,
        tenant_id: UUID,
        waybill_id: UUID,
        *,
        version_id: int,
        actor_user_id: UUID,
        reason: str,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            waybill = await session.get(
                LogisticsWaybill, waybill_id, with_for_update=True
            )
            if waybill is None:
                raise LogisticsShippingNotFoundError("Waybill was not found.")
            if waybill.version_id != version_id:
                raise LogisticsShippingConflictError("The waybill has changed.")
            if not waybill.is_current or waybill.status not in {
                "created",
                "label_ready",
            }:
                raise LogisticsShippingConflictError("The waybill cannot be cancelled.")
            package = await session.get(
                LogisticsPackage, waybill.package_id, with_for_update=True
            )
            if package is None:
                raise LogisticsShippingNotFoundError("Package was not found.")
            task = await load_task(session, package.task_id)
            previous = task.status
            waybill.status = "cancelled"
            waybill.is_current = False
            package.status = "packed"
            task.status = "pending_waybill"
            task.updated_at = datetime.now(UTC)
            session.add(
                operation(
                    tenant_id,
                    task.id,
                    actor_user_id,
                    "waybill_cancelled",
                    previous,
                    task.status,
                    {
                        "packageId": str(package.id),
                        "waybillId": str(waybill.id),
                        "reason": reason,
                    },
                )
            )
            await commit(session)
            await session.refresh(waybill)
            return waybill_record(waybill)
        raise RuntimeError("Tenant database session was not created.")

    def _encrypt(self, tracking_number: str | None) -> str | None:
        if not tracking_number or self._tracking_cipher is None:
            return None
        return self._tracking_cipher.encrypt(tracking_number)
