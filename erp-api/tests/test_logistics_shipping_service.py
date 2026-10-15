from uuid import uuid4

import pytest

from erp_api.services.carrier_adapter import CarrierInput, ParcelInput, ServiceInput
from erp_api.services.logistics_shipping_context import (
    ShippingContext,
    StoredWaybillContext,
)
from erp_api.services.logistics_shipping_errors import LogisticsShippingConflictError
from erp_api.services.logistics_shipping_service import LogisticsShippingService


class FakeRepository:
    def __init__(self) -> None:
        self.context = ShippingContext(
            ParcelInput(uuid4(), 1200, 200, 150, 100, "US", "package:v1"),
            CarrierInput(uuid4(), "MANUAL", "Manual", "manual"),
            ServiceInput(
                uuid4(),
                "STANDARD",
                "Standard",
                "standard",
                ("US",),
                {
                    "manual_pricing": {
                        "base_fee_minor": 500,
                        "per_kg_fee_minor": 200,
                        "currency": "USD",
                    }
                },
            ),
            None,
        )
        self.persisted = False
        self.cancelled = False

    async def load_contexts(self, tenant_id, package_id, **kwargs):
        return [self.context]

    async def persist_waybill(self, tenant_id, context, result, **kwargs):
        self.persisted = True
        return {"trackingNumberMasked": "TR****3456", "status": "label_ready"}

    async def load_waybill(self, tenant_id, waybill_id):
        return StoredWaybillContext(
            waybill_id,
            self.context.carrier,
            self.context.service,
            None,
            None,
            "https://labels.test/1.pdf",
            2,
            "label_ready",
        )

    async def cancel_waybill(self, tenant_id, waybill_id, **kwargs):
        self.cancelled = True
        return {"status": "cancelled"}


@pytest.mark.asyncio
async def test_shipping_service_quotes_and_creates_through_manual_adapter() -> None:
    repository = FakeRepository()
    service = LogisticsShippingService(repository)  # type: ignore[arg-type]

    quotes = await service.quote(
        uuid4(),
        repository.context.parcel.package_id,
        carrier_id=repository.context.carrier.id,
        service_id=repository.context.service.id,
        account_id=None,
    )
    created = await service.create_waybill(
        uuid4(),
        repository.context.parcel.package_id,
        actor_user_id=uuid4(),
        carrier_id=repository.context.carrier.id,
        service_id=repository.context.service.id,
        account_id=None,
        tracking_number="TRACK-123456",
        external_waybill_id=None,
        label_url="https://labels.test/1.pdf",
    )

    assert quotes[0]["amountMinor"] == 900
    assert created["status"] == "label_ready"
    assert repository.persisted is True


@pytest.mark.asyncio
async def test_shipping_service_rejects_stale_cancel_before_adapter_call() -> None:
    repository = FakeRepository()
    service = LogisticsShippingService(repository)  # type: ignore[arg-type]

    with pytest.raises(LogisticsShippingConflictError):
        await service.cancel_waybill(
            uuid4(),
            uuid4(),
            actor_user_id=uuid4(),
            version_id=1,
            reason="stale request",
        )

    assert repository.cancelled is False
