from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class PlatformFulfillmentError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class PlatformFulfillmentCommand:
    event_id: UUID
    tenant_id: UUID
    shop_id: UUID
    platform: str
    platform_order_id: str
    platform_package_id: str | None
    tracking_number: str
    platform_carrier_id: str | None
    shipped_at: datetime
    idempotency_key: str


@dataclass(frozen=True)
class PlatformFulfillmentResult:
    platform_request_id: str | None = None


class PlatformFulfillmentAdapter(Protocol):
    platform: str

    async def fulfill(
        self, command: PlatformFulfillmentCommand
    ) -> PlatformFulfillmentResult: ...


class PlatformFulfillmentAdapterRegistry:
    def __init__(self, adapters: list[PlatformFulfillmentAdapter]) -> None:
        self._adapters: dict[str, PlatformFulfillmentAdapter] = {}
        for adapter in adapters:
            platform = adapter.platform.strip().lower()
            if not platform:
                raise ValueError("Platform fulfillment adapter name cannot be blank.")
            if platform in self._adapters:
                raise ValueError(f"Duplicate platform fulfillment adapter: {platform}.")
            self._adapters[platform] = adapter

    def get(self, platform: str) -> PlatformFulfillmentAdapter:
        normalized = platform.strip().lower()
        adapter = self._adapters.get(normalized)
        if adapter is None:
            raise PlatformFulfillmentError(
                f"Platform fulfillment adapter is unavailable for {normalized}.",
                code="platform_adapter_unavailable",
                retryable=False,
            )
        return adapter
