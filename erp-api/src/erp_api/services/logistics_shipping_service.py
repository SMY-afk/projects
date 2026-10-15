from __future__ import annotations

from uuid import UUID

from erp_api.services.carrier_adapter import WaybillDraft
from erp_api.services.carrier_adapter_registry import CarrierAdapterRegistry
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_shipping_repository import LogisticsShippingRepository


class LogisticsShippingService:
    def __init__(
        self,
        repository: LogisticsShippingRepository,
        adapters: CarrierAdapterRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._adapters = adapters or CarrierAdapterRegistry()

    async def quote(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        carrier_id: UUID | None,
        service_id: UUID | None,
        account_id: UUID | None,
    ) -> list[dict[str, object]]:
        contexts = await self._repository.load_contexts(
            tenant_id,
            package_id,
            carrier_id=carrier_id,
            service_id=service_id,
            account_id=account_id,
        )
        records: list[dict[str, object]] = []
        last_error: LogisticsShippingValidationError | None = None
        for context in contexts:
            try:
                result = await self._adapters.get(context.carrier.adapter_key).quote(
                    context.parcel,
                    context.carrier,
                    context.service,
                    context.account,
                )
            except LogisticsShippingValidationError as error:
                last_error = error
                continue
            records.append(
                {
                    "carrierId": context.carrier.id,
                    "carrierName": context.carrier.name,
                    "serviceId": context.service.id,
                    "serviceName": context.service.name,
                    "accountId": context.account.id if context.account else None,
                    "amountMinor": result.amount_minor,
                    "currency": result.currency,
                    "estimatedDaysMin": result.estimated_days_min,
                    "estimatedDaysMax": result.estimated_days_max,
                    "quoteType": result.quote_type,
                    "warnings": list(result.warnings),
                }
            )
        if not records and last_error is not None:
            raise last_error
        return records

    async def create_waybill(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        carrier_id: UUID,
        service_id: UUID,
        account_id: UUID | None,
        tracking_number: str | None,
        external_waybill_id: str | None,
        label_url: str | None,
    ) -> dict[str, object]:
        contexts = await self._repository.load_contexts(
            tenant_id,
            package_id,
            carrier_id=carrier_id,
            service_id=service_id,
            account_id=account_id,
        )
        context = contexts[0]
        result = await self._adapters.get(context.carrier.adapter_key).create_waybill(
            context.parcel,
            context.carrier,
            context.service,
            context.account,
            WaybillDraft(
                tracking_number,
                external_waybill_id,
                label_url,
                _label_format(label_url),
            ),
        )
        return await self._repository.persist_waybill(
            tenant_id, context, result, actor_user_id=actor_user_id
        )

    async def cancel_waybill(
        self,
        tenant_id: UUID,
        waybill_id: UUID,
        *,
        actor_user_id: UUID,
        version_id: int,
        reason: str,
    ) -> dict[str, object]:
        context = await self._repository.load_waybill(tenant_id, waybill_id)
        if context.version_id != version_id:
            raise LogisticsShippingConflictError("The waybill has changed.")
        if context.status not in {"created", "label_ready"}:
            raise LogisticsShippingConflictError("The waybill cannot be cancelled.")
        reason = reason.strip()
        if not reason:
            raise LogisticsShippingValidationError("Cancellation reason is required.")
        await self._adapters.get(context.carrier.adapter_key).cancel_waybill(
            context.carrier,
            context.service,
            context.account,
            context.external_waybill_id,
        )
        return await self._repository.cancel_waybill(
            tenant_id,
            waybill_id,
            version_id=version_id,
            actor_user_id=actor_user_id,
            reason=reason,
        )

    async def get_label(self, tenant_id: UUID, waybill_id: UUID) -> dict[str, object]:
        context = await self._repository.load_waybill(tenant_id, waybill_id)
        label = await self._adapters.get(context.carrier.adapter_key).get_label(
            context.carrier,
            context.service,
            context.account,
            context.external_waybill_id,
            context.label_url,
            _label_format(context.label_url),
        )
        return {
            "waybillId": context.id,
            "kind": "url",
            "url": label.url,
            "format": label.format,
        }


def _label_format(url: str | None) -> str | None:
    if not url:
        return None
    clean = url.split("?", 1)[0].lower()
    for value in ("pdf", "png", "zpl"):
        if clean.endswith(f".{value}"):
            return value
    return None
