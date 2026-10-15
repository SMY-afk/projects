from __future__ import annotations

from math import ceil

from erp_api.services.carrier_adapter import (
    AccountInput,
    CarrierInput,
    LabelResult,
    ParcelInput,
    QuoteResult,
    ServiceInput,
    WaybillDraft,
    WaybillResult,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)


class ManualCarrierAdapter:
    key = "manual"

    async def quote(
        self,
        parcel: ParcelInput,
        carrier: CarrierInput,
        service: ServiceInput,
        account: AccountInput | None,
    ) -> QuoteResult:
        del carrier, account
        if (
            service.supported_countries
            and parcel.destination_country not in service.supported_countries
        ):
            raise LogisticsShippingValidationError(
                "Carrier service does not support the destination country."
            )
        pricing = service.configuration.get("manual_pricing")
        if not isinstance(pricing, dict):
            return QuoteResult(
                amount_minor=None,
                currency=None,
                estimated_days_min=None,
                estimated_days_max=None,
                quote_type="manual",
                warnings=("Manual freight quote is required.",),
            )
        base = _non_negative_int(pricing.get("base_fee_minor"), "base fee")
        per_kg = _non_negative_int(pricing.get("per_kg_fee_minor"), "per-kg fee")
        currency = str(pricing.get("currency", "")).strip().upper()
        if len(currency) != 3:
            raise LogisticsShippingValidationError(
                "Manual pricing currency must use a three-letter code."
            )
        return QuoteResult(
            amount_minor=base + ceil(parcel.weight_grams / 1000) * per_kg,
            currency=currency,
            estimated_days_min=_optional_int(pricing.get("estimated_days_min")),
            estimated_days_max=_optional_int(pricing.get("estimated_days_max")),
            quote_type="calculated",
        )

    async def create_waybill(
        self,
        parcel: ParcelInput,
        carrier: CarrierInput,
        service: ServiceInput,
        account: AccountInput | None,
        draft: WaybillDraft,
    ) -> WaybillResult:
        del parcel, carrier, service, account
        tracking_number = (draft.tracking_number or "").strip()
        if not tracking_number:
            raise LogisticsShippingValidationError(
                "Manual waybill requires a tracking number."
            )
        return WaybillResult(
            tracking_number=tracking_number,
            external_waybill_id=draft.external_waybill_id,
            label_url=draft.label_url,
            label_format=draft.label_format,
        )

    async def cancel_waybill(
        self,
        carrier: CarrierInput,
        service: ServiceInput | None,
        account: AccountInput | None,
        external_waybill_id: str | None,
    ) -> None:
        del carrier, service, account, external_waybill_id

    async def get_label(
        self,
        carrier: CarrierInput,
        service: ServiceInput | None,
        account: AccountInput | None,
        external_waybill_id: str | None,
        label_url: str | None,
        label_format: str | None,
    ) -> LabelResult:
        del carrier, service, account, external_waybill_id
        if not label_url:
            raise LogisticsShippingNotFoundError("Waybill label is not available.")
        return LabelResult(url=label_url, format=label_format)


def _non_negative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LogisticsShippingValidationError(
            f"Manual pricing {label} must be a non-negative integer."
        )
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LogisticsShippingValidationError(
            "Estimated delivery days must be a non-negative integer."
        )
    return value
