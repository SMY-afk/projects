import asyncio
from uuid import uuid4

import pytest

from erp_api.services.carrier_adapter import (
    CarrierInput,
    ParcelInput,
    ServiceInput,
    WaybillDraft,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.manual_carrier_adapter import ManualCarrierAdapter


def _parcel(country: str | None = "US") -> ParcelInput:
    return ParcelInput(uuid4(), 1200, 200, 150, 100, country, "package:v1")


def _carrier() -> CarrierInput:
    return CarrierInput(uuid4(), "MANUAL", "Manual carrier", "manual")


def _service(configuration: dict[str, object]) -> ServiceInput:
    return ServiceInput(
        uuid4(), "STANDARD", "Standard", "standard", ("US",), configuration
    )


def test_manual_adapter_calculates_configured_freight_by_started_kilogram():
    quote = asyncio.run(
        ManualCarrierAdapter().quote(
            _parcel(),
            _carrier(),
            _service(
                {
                    "manual_pricing": {
                        "base_fee_minor": 500,
                        "per_kg_fee_minor": 200,
                        "currency": "usd",
                        "estimated_days_min": 2,
                        "estimated_days_max": 4,
                    }
                }
            ),
            None,
        )
    )

    assert quote.amount_minor == 900
    assert quote.currency == "USD"
    assert quote.estimated_days_min == 2
    assert quote.quote_type == "calculated"


def test_manual_adapter_marks_unconfigured_rate_as_manual_quote():
    quote = asyncio.run(
        ManualCarrierAdapter().quote(_parcel(), _carrier(), _service({}), None)
    )

    assert quote.amount_minor is None
    assert quote.quote_type == "manual"
    assert quote.warnings == ("Manual freight quote is required.",)


def test_manual_adapter_requires_tracking_and_returns_optional_label():
    adapter = ManualCarrierAdapter()
    with pytest.raises(LogisticsShippingValidationError):
        asyncio.run(
            adapter.create_waybill(
                _parcel(),
                _carrier(),
                _service({}),
                None,
                WaybillDraft(None, None, None, None),
            )
        )

    created = asyncio.run(
        adapter.create_waybill(
            _parcel(),
            _carrier(),
            _service({}),
            None,
            WaybillDraft(" TRACK-123 ", None, "https://labels.test/1.pdf", "pdf"),
        )
    )
    label = asyncio.run(
        adapter.get_label(
            _carrier(),
            _service({}),
            None,
            created.external_waybill_id,
            created.label_url,
            created.label_format,
        )
    )

    assert created.tracking_number == "TRACK-123"
    assert label.url == "https://labels.test/1.pdf"
    with pytest.raises(LogisticsShippingNotFoundError):
        asyncio.run(adapter.get_label(_carrier(), _service({}), None, None, None, None))
