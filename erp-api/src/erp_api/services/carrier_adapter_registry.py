from erp_api.services.carrier_adapter import CarrierAdapter
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingValidationError,
)
from erp_api.services.manual_carrier_adapter import ManualCarrierAdapter


class CarrierAdapterRegistry:
    def __init__(self, adapters: list[CarrierAdapter] | None = None) -> None:
        installed = adapters or [ManualCarrierAdapter()]
        self._adapters = {adapter.key: adapter for adapter in installed}

    def get(self, key: str) -> CarrierAdapter:
        adapter = self._adapters.get(key)
        if adapter is None:
            raise LogisticsShippingValidationError(
                f"Carrier adapter '{key}' is not installed."
            )
        return adapter
