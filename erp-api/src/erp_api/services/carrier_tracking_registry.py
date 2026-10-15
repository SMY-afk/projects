from erp_api.services.carrier_tracking_adapter import (
    CarrierTrackingAdapter,
    GenericCarrierTrackingAdapter,
)
from erp_api.services.logistics_shipping_errors import LogisticsShippingValidationError


class CarrierTrackingAdapterRegistry:
    def __init__(self, adapters: list[CarrierTrackingAdapter] | None = None) -> None:
        installed = adapters or [GenericCarrierTrackingAdapter()]
        self._adapters = {adapter.key: adapter for adapter in installed}

    def get(self, key: str) -> CarrierTrackingAdapter:
        adapter = self._adapters.get(key)
        if adapter is None:
            raise LogisticsShippingValidationError(
                f"Carrier tracking adapter '{key}' is not installed."
            )
        return adapter
