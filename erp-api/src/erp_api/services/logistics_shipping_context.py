from dataclasses import dataclass
from uuid import UUID

from erp_api.services.carrier_adapter import (
    AccountInput,
    CarrierInput,
    ParcelInput,
    ServiceInput,
)


@dataclass(frozen=True)
class ShippingContext:
    parcel: ParcelInput
    carrier: CarrierInput
    service: ServiceInput
    account: AccountInput | None


@dataclass(frozen=True)
class StoredWaybillContext:
    id: UUID
    carrier: CarrierInput
    service: ServiceInput | None
    account: AccountInput | None
    external_waybill_id: str | None
    label_url: str | None
    version_id: int
    status: str
