from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_carrier import LogisticsCarrier, LogisticsCarrierService
from erp_api.models.logistics_platform_carrier_mapping import (
    LogisticsPlatformCarrierMapping,
)
from erp_api.models.shop import Shop
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_shipping_records import mapping_record


class LogisticsCarrierMappingRepositoryMixin:
    _database: Database

    async def create_platform_mapping(
        self,
        tenant_id: UUID,
        carrier_id: UUID,
        *,
        store_id: UUID,
        platform: str,
        region: str,
        service_id: UUID | None,
        platform_carrier_id: str,
        platform_carrier_code: str | None,
        platform_carrier_name: str | None,
        delivery_option_id: str | None,
        raw_payload: dict[str, object],
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            carrier = await session.get(LogisticsCarrier, carrier_id)
            if carrier is None:
                raise LogisticsShippingNotFoundError("Carrier was not found.")
            await _validate_store(session, store_id, platform)
            await _validate_service(session, carrier_id, service_id)
            await _ensure_mapping_available(
                session,
                carrier_id=carrier_id,
                service_id=service_id,
                store_id=store_id,
                platform=platform,
                delivery_option_id=delivery_option_id,
                platform_carrier_id=platform_carrier_id,
            )
            mapping = LogisticsPlatformCarrierMapping(
                tenant_id=tenant_id,
                carrier_id=carrier_id,
                service_id=service_id,
                store_id=store_id,
                platform=platform,
                region=region,
                platform_carrier_id=platform_carrier_id,
                platform_carrier_code=platform_carrier_code,
                platform_carrier_name=platform_carrier_name,
                delivery_option_id=delivery_option_id,
                raw_payload=raw_payload,
                status="active",
            )
            session.add(mapping)
            await session.commit()
            await session.refresh(mapping)
            return mapping_record(mapping)
        raise RuntimeError("Tenant database session was not created.")

    async def update_platform_mapping(
        self,
        tenant_id: UUID,
        mapping_id: UUID,
        *,
        version_id: int,
        status: str | None,
        platform_carrier_id: str | None,
        platform_carrier_code: str | None,
        platform_carrier_name: str | None,
        delivery_option_id: str | None,
        raw_payload: dict[str, object] | None,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            mapping = await session.scalar(
                select(LogisticsPlatformCarrierMapping)
                .where(LogisticsPlatformCarrierMapping.id == mapping_id)
                .with_for_update()
            )
            if mapping is None:
                raise LogisticsShippingNotFoundError(
                    "Platform carrier mapping was not found."
                )
            if mapping.version_id != version_id:
                raise LogisticsShippingConflictError(
                    "Platform carrier mapping was updated by another user."
                )
            if status is not None:
                mapping.status = status
            if platform_carrier_id is not None or delivery_option_id is not None:
                next_provider_id = platform_carrier_id or mapping.platform_carrier_id
                next_delivery_option_id = (
                    delivery_option_id
                    if delivery_option_id is not None
                    else mapping.delivery_option_id
                )
                await _ensure_mapping_available(
                    session,
                    carrier_id=mapping.carrier_id,
                    service_id=mapping.service_id,
                    store_id=mapping.store_id,
                    platform=mapping.platform,
                    delivery_option_id=next_delivery_option_id,
                    platform_carrier_id=next_provider_id,
                    exclude_id=mapping.id,
                )
                mapping.platform_carrier_id = next_provider_id
                mapping.delivery_option_id = next_delivery_option_id
            if platform_carrier_code is not None:
                mapping.platform_carrier_code = platform_carrier_code
            if platform_carrier_name is not None:
                mapping.platform_carrier_name = platform_carrier_name
            if raw_payload is not None:
                mapping.raw_payload = raw_payload
            await session.commit()
            await session.refresh(mapping)
            return mapping_record(mapping)
        raise RuntimeError("Tenant database session was not created.")


async def _validate_service(session, carrier_id: UUID, service_id: UUID | None) -> None:
    if service_id is None:
        return
    service = await session.scalar(
        select(LogisticsCarrierService.id).where(
            LogisticsCarrierService.id == service_id,
            LogisticsCarrierService.carrier_id == carrier_id,
        )
    )
    if service is None:
        raise LogisticsShippingValidationError(
            "Carrier service does not belong to this carrier."
        )


async def _validate_store(session, store_id: UUID, platform: str) -> None:
    store = await session.get(Shop, store_id)
    if store is None:
        raise LogisticsShippingNotFoundError("Store was not found.")
    if store.platform.strip().lower() != platform:
        raise LogisticsShippingValidationError(
            "Store platform does not match the carrier mapping platform."
        )


async def _ensure_mapping_available(
    session,
    *,
    carrier_id: UUID,
    service_id: UUID | None,
    store_id: UUID,
    platform: str,
    delivery_option_id: str | None,
    platform_carrier_id: str,
    exclude_id: UUID | None = None,
) -> None:
    await _ensure_external_id_available(
        session,
        store_id=store_id,
        platform=platform,
        delivery_option_id=delivery_option_id,
        platform_carrier_id=platform_carrier_id,
        exclude_id=exclude_id,
    )
    scope_query = select(LogisticsPlatformCarrierMapping.id).where(
        LogisticsPlatformCarrierMapping.store_id == store_id,
        LogisticsPlatformCarrierMapping.platform == platform,
        LogisticsPlatformCarrierMapping.delivery_option_id.is_(delivery_option_id)
        if delivery_option_id is None
        else LogisticsPlatformCarrierMapping.delivery_option_id == delivery_option_id,
    )
    if exclude_id is not None:
        scope_query = scope_query.where(
            LogisticsPlatformCarrierMapping.id != exclude_id
        )
    if service_id is None:
        scope_query = scope_query.where(
            LogisticsPlatformCarrierMapping.carrier_id == carrier_id,
            LogisticsPlatformCarrierMapping.service_id.is_(None),
        )
    else:
        scope_query = scope_query.where(
            LogisticsPlatformCarrierMapping.service_id == service_id
        )
    if await session.scalar(scope_query) is not None:
        raise LogisticsShippingConflictError(
            "Carrier scope already has a platform mapping."
        )


async def _ensure_external_id_available(
    session,
    *,
    store_id: UUID,
    platform: str,
    delivery_option_id: str | None,
    platform_carrier_id: str,
    exclude_id: UUID | None = None,
) -> None:
    query = select(LogisticsPlatformCarrierMapping.id).where(
        LogisticsPlatformCarrierMapping.store_id == store_id,
        LogisticsPlatformCarrierMapping.platform == platform,
        LogisticsPlatformCarrierMapping.platform_carrier_id == platform_carrier_id,
        LogisticsPlatformCarrierMapping.delivery_option_id.is_(delivery_option_id)
        if delivery_option_id is None
        else LogisticsPlatformCarrierMapping.delivery_option_id == delivery_option_id,
    )
    if exclude_id is not None:
        query = query.where(LogisticsPlatformCarrierMapping.id != exclude_id)
    if await session.scalar(query) is not None:
        raise LogisticsShippingConflictError(
            "Platform carrier ID is already mapped for this store and delivery option."
        )
