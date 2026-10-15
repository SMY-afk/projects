from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ParcelInput:
    package_id: UUID
    weight_grams: int
    length_mm: int
    width_mm: int
    height_mm: int
    destination_country: str | None
    idempotency_key: str


@dataclass(frozen=True)
class CarrierInput:
    id: UUID
    code: str
    name: str
    adapter_key: str


@dataclass(frozen=True)
class ServiceInput:
    id: UUID
    code: str
    name: str
    service_level: str | None
    supported_countries: tuple[str, ...]
    configuration: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountInput:
    id: UUID
    auth_type: str
    secret_reference: str | None


@dataclass(frozen=True)
class QuoteResult:
    amount_minor: int | None
    currency: str | None
    estimated_days_min: int | None
    estimated_days_max: int | None
    quote_type: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class WaybillDraft:
    tracking_number: str | None
    external_waybill_id: str | None
    label_url: str | None
    label_format: str | None


@dataclass(frozen=True)
class WaybillResult:
    tracking_number: str | None
    external_waybill_id: str | None
    label_url: str | None
    label_format: str | None


@dataclass(frozen=True)
class LabelResult:
    url: str
    format: str | None


class CarrierAdapter(Protocol):
    key: str

    async def quote(
        self,
        parcel: ParcelInput,
        carrier: CarrierInput,
        service: ServiceInput,
        account: AccountInput | None,
    ) -> QuoteResult: ...

    async def create_waybill(
        self,
        parcel: ParcelInput,
        carrier: CarrierInput,
        service: ServiceInput,
        account: AccountInput | None,
        draft: WaybillDraft,
    ) -> WaybillResult: ...

    async def cancel_waybill(
        self,
        carrier: CarrierInput,
        service: ServiceInput | None,
        account: AccountInput | None,
        external_waybill_id: str | None,
    ) -> None: ...

    async def get_label(
        self,
        carrier: CarrierInput,
        service: ServiceInput | None,
        account: AccountInput | None,
        external_waybill_id: str | None,
        label_url: str | None,
        label_format: str | None,
    ) -> LabelResult: ...
