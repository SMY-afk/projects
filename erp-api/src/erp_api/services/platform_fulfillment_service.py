from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.platform_fulfillment_adapter import (
    PlatformFulfillmentAdapterRegistry,
    PlatformFulfillmentError,
)
from erp_api.services.platform_fulfillment_outbox_repository import (
    PlatformFulfillmentOutboxRepository,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRateLimitError,
    TikTokTimeoutError,
)

_RETRYABLE_TIKTOK_CODES = frozenset(
    {
        "invalid_response",
        "36009003",
        "11001031",
        "21001003",
        "21001011",
        "21001028",
        "21022029",
        "21042001",
        "21042076",
    }
)
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class PlatformFulfillmentProcessResult:
    status: str
    attempt_count: int
    retry_after_seconds: float | None = None


class PlatformFulfillmentService:
    def __init__(
        self,
        repository: PlatformFulfillmentOutboxRepository,
        adapters: PlatformFulfillmentAdapterRegistry,
        *,
        max_tries: int,
        retry_base_seconds: int,
        processing_timeout: timedelta,
    ) -> None:
        self._repository = repository
        self._adapters = adapters
        self._max_tries = max_tries
        self._retry_base_seconds = retry_base_seconds
        self.processing_timeout = processing_timeout

    async def process(
        self, tenant_id: UUID, event_id: UUID
    ) -> PlatformFulfillmentProcessResult:
        claimed = await self._repository.claim(
            tenant_id, event_id, processing_timeout=self.processing_timeout
        )
        if claimed is None:
            return PlatformFulfillmentProcessResult("ignored", 0)
        try:
            command = await self._repository.load_command(tenant_id, event_id)
            result = await self._adapters.get(command.platform).fulfill(command)
        except Exception as error:  # noqa: BLE001 - persist every worker failure safely
            code, retryable = _classify_error(error)
            should_retry = retryable and claimed.attempt_count < self._max_tries
            delay = self._retry_delay(claimed.attempt_count) if should_retry else None
            await self._repository.fail(
                tenant_id,
                event_id,
                code=code,
                summary=f"{type(error).__name__}: platform fulfillment failed",
                retry_at=(
                    datetime.now(UTC) + timedelta(seconds=delay) if delay else None
                ),
            )
            return PlatformFulfillmentProcessResult(
                "retry_wait" if should_retry else "failed",
                claimed.attempt_count,
                delay,
            )
        await self._repository.succeed(tenant_id, event_id, result.platform_request_id)
        return PlatformFulfillmentProcessResult("succeeded", claimed.attempt_count)

    def _retry_delay(self, attempt: int) -> float:
        return float(min(1800, self._retry_base_seconds * (2 ** max(0, attempt - 1))))


def _classify_error(error: Exception) -> tuple[str, bool]:
    if isinstance(error, PlatformFulfillmentError):
        return error.code, error.retryable
    if isinstance(error, TikTokRateLimitError):
        return "rate_limited", True
    if isinstance(error, TikTokTimeoutError):
        return "timeout", True
    if isinstance(error, TikTokApiError):
        upstream_status = (
            error.upstream_status_code
            if error.upstream_status_code is not None
            else error.status_code
        )
        retryable = (
            upstream_status in _RETRYABLE_HTTP_STATUSES
            or error.code in _RETRYABLE_TIKTOK_CODES
        )
        return f"tiktok_api_{error.code}"[:64], retryable
    if isinstance(error, TikTokClientError):
        return "platform_transport_error", True
    return "unexpected_error", True
