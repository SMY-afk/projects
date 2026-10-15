from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_carrier import (
    LogisticsCarrier,
    LogisticsCarrierAccount,
    LogisticsCarrierService,
)
from erp_api.models.logistics_platform_carrier_mapping import (
    LogisticsPlatformCarrierMapping,
)
from erp_api.services.logistics_carrier_mapping_repository import (
    LogisticsCarrierMappingRepositoryMixin,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
)
from erp_api.services.logistics_shipping_records import (
    account_record,
    carrier_record,
    service_record,
)


class LogisticsCarrierRepository(LogisticsCarrierMappingRepositoryMixin):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_carriers(self, tenant_id: UUID) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            carriers = await session.scalars(
                _carrier_select().order_by(LogisticsCarrier.name, LogisticsCarrier.id)
            )
            carrier_items = carriers.unique().all()
            mappings = (
                await session.scalars(
                    select(LogisticsPlatformCarrierMapping).order_by(
                        LogisticsPlatformCarrierMapping.platform,
                        LogisticsPlatformCarrierMapping.region,
                        LogisticsPlatformCarrierMapping.platform_carrier_code,
                    )
                )
            ).all()
            mappings_by_carrier: dict[UUID, list[LogisticsPlatformCarrierMapping]] = {}
            for mapping in mappings:
                mappings_by_carrier.setdefault(mapping.carrier_id, []).append(mapping)
            return [
                carrier_record(item, mappings_by_carrier.get(item.id, []))
                for item in carrier_items
            ]
        return []

    async def create_carrier(
        self,
        tenant_id: UUID,
        *,
        code: str,
        name: str,
        adapter_key: str,
        tracking_url_template: str | None,
    ) -> dict[str, object]:
        normalized_code = code.strip().upper()
        async for session in self._database.session(tenant_id):
            duplicate = await session.scalar(
                select(LogisticsCarrier.id).where(
                    LogisticsCarrier.code == normalized_code
                )
            )
            if duplicate is not None:
                raise LogisticsShippingConflictError("Carrier code already exists.")
            carrier = LogisticsCarrier(
                tenant_id=tenant_id,
                code=normalized_code,
                name=name.strip(),
                adapter_key=adapter_key.strip().lower(),
                tracking_url_template=tracking_url_template,
                status="active",
            )
            session.add(carrier)
            await session.commit()
            stored = await _load_carrier(session, carrier.id)
            if stored is None:
                raise RuntimeError("Created carrier could not be reloaded.")
            return carrier_record(stored)
        raise RuntimeError("Tenant database session was not created.")

    async def create_service(
        self,
        tenant_id: UUID,
        carrier_id: UUID,
        *,
        code: str,
        name: str,
        service_level: str | None,
        supported_countries: list[str],
        manual_pricing: dict[str, object] | None,
        platform_provider_ids: dict[str, str],
        tracking_status_map: dict[str, str],
    ) -> dict[str, object]:
        normalized_code = code.strip().upper()
        async for session in self._database.session(tenant_id):
            carrier = await session.get(LogisticsCarrier, carrier_id)
            if carrier is None:
                raise LogisticsShippingNotFoundError("Carrier was not found.")
            duplicate = await session.scalar(
                select(LogisticsCarrierService.id).where(
                    LogisticsCarrierService.carrier_id == carrier_id,
                    LogisticsCarrierService.code == normalized_code,
                )
            )
            if duplicate is not None:
                raise LogisticsShippingConflictError("Carrier service code exists.")
            service = LogisticsCarrierService(
                tenant_id=tenant_id,
                carrier_id=carrier_id,
                code=normalized_code,
                name=name.strip(),
                service_level=service_level,
                supported_countries=sorted(
                    {
                        item.strip().upper()
                        for item in supported_countries
                        if item.strip()
                    }
                ),
                configuration={
                    **(
                        {"manual_pricing": manual_pricing}
                        if manual_pricing is not None
                        else {}
                    ),
                    **{
                        f"{platform}ShippingProviderId": provider_id
                        for platform, provider_id in platform_provider_ids.items()
                    },
                    **(
                        {"trackingStatusMap": tracking_status_map}
                        if tracking_status_map
                        else {}
                    ),
                },
                status="active",
            )
            session.add(service)
            await session.commit()
            await session.refresh(service)
            return service_record(service)
        raise RuntimeError("Tenant database session was not created.")

    async def create_account(
        self,
        tenant_id: UUID,
        carrier_id: UUID,
        *,
        account_name: str,
        account_identifier_masked: str | None,
        auth_type: str,
        secret_reference: str | None,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            carrier = await session.get(LogisticsCarrier, carrier_id)
            if carrier is None:
                raise LogisticsShippingNotFoundError("Carrier was not found.")
            duplicate = await session.scalar(
                select(LogisticsCarrierAccount.id).where(
                    LogisticsCarrierAccount.carrier_id == carrier_id,
                    LogisticsCarrierAccount.account_name == account_name.strip(),
                )
            )
            if duplicate is not None:
                raise LogisticsShippingConflictError("Carrier account name exists.")
            account = LogisticsCarrierAccount(
                tenant_id=tenant_id,
                carrier_id=carrier_id,
                account_name=account_name.strip(),
                account_identifier_masked=account_identifier_masked,
                auth_type=auth_type,
                secret_reference=secret_reference,
                status="active",
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account_record(account)
        raise RuntimeError("Tenant database session was not created.")


def _carrier_select():
    return select(LogisticsCarrier).options(
        selectinload(LogisticsCarrier.services),
        selectinload(LogisticsCarrier.accounts),
    )


async def _load_carrier(session, carrier_id: UUID) -> LogisticsCarrier | None:
    return await session.scalar(
        _carrier_select()
        .where(LogisticsCarrier.id == carrier_id)
        .execution_options(populate_existing=True)
    )
