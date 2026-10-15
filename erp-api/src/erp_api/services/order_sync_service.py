from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.external_order_evidence import (
    PLATFORM_NO_ORDER_LEVEL_EVIDENCE,
    UNSUPPORTED_ENDPOINT,
    ExternalOrderEvidenceLookup,
)
from erp_api.services.order_repository import OrderRepository
from erp_api.services.order_sync_repository import OrderSyncRepository, OrderSyncResult
from erp_api.services.tiktok_ads_order_client import TikTokAdsOrderClient
from erp_api.services.tiktok_affiliate_order_client import TikTokAffiliateOrderClient
from erp_api.services.tiktok_client import TikTokClient
from erp_api.services.tiktok_order_client import TikTokOrderClient
from erp_api.services.tiktok_order_schemas import TikTokOrder
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    tiktok_request_context,
)

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(access[_ -]?token|refresh[_ -]?token|auth(?:orization)?[_ -]?code|shop[_ -]?cipher)"
    r"\b\s*(?:[:=]|\bis\s+)?\s*['\"]?[^\s,'\";]+['\"]?|\bbearer\s+[^\s,;]+"
)


class OrderSyncWindowError(ValueError):
    """Raised when a sync window violates the staged backfill policy."""


_WINDOW_CLOCK_SKEW = timedelta(minutes=1)
logger = logging.getLogger("erp_api.order_sync")


class OrderSyncService:
    def __init__(
        self,
        repository: OrderSyncRepository,
        order_repository: OrderRepository,
        shop_repository,
        client: TikTokClient,
        order_client: TikTokOrderClient,
        initial_backfill_days: int = 30,
        max_backfill_days: int = 30,
        affiliate_order_client: TikTokAffiliateOrderClient | None = None,
        ads_order_client: TikTokAdsOrderClient | None = None,
        ads_access_token: str | None = None,
    ) -> None:
        self._repository = repository
        self._order_repository = order_repository
        self._shop_repository = shop_repository
        self._client = client
        self._order_client = order_client
        self._initial_backfill_days = initial_backfill_days
        self._max_backfill_days = max_backfill_days
        self._affiliate_order_client = affiliate_order_client
        self._ads_order_client = ads_order_client
        self._ads_access_token = ads_access_token

    async def sync_orders(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        trigger: str = "manual",
        mode: str = "incremental",
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        platform_order_ids: set[str] | None = None,
    ) -> OrderSyncResult:
        shop_data = await self._shop_repository.get_authorized_tiktok_shop(
            tenant_id, shop_id
        )
        if shop_data is None:
            raise RuntimeError(
                "No authorized TikTok shop is available for this tenant."
            )
        access_token = await self._shop_repository.get_access_token(tenant_id, shop_id)
        connection = await self._shop_repository.get_connection_tokens(
            tenant_id, shop_id
        )
        if not access_token or not connection:
            raise RuntimeError("TikTok connection credentials are unavailable.")
        shop = AuthorizedOrderShop(
            id=shop_id,
            access_token=access_token,
            refresh_token=connection[0],
            expires_at=connection[1],
            shop_cipher=connection[2],
        )
        cursor = await self._repository.get_cursor(tenant_id, shop.id)
        start, end = self._resolve_window(
            mode=mode,
            updated_from=updated_from,
            updated_to=updated_to,
            last_success_at=cursor.last_success_at,
        )
        access_token = await self._access_token(tenant_id, shop)
        run_id = await self._repository.create_run(
            tenant_id,
            shop.id,
            trigger=trigger,
            mode=mode,
            window_from=start,
            window_to=end,
        )
        try:
            with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop.id)):
                async for page in self._order_client.iter_order_pages(
                    access_token,
                    shop_cipher=shop.shop_cipher or "",
                    page_token=None,
                    updated_from=start,
                    updated_to=end,
                ):
                    page_orders = (
                        page.orders
                        if platform_order_ids is None
                        else [
                            order
                            for order in page.orders
                            if order.platform_order_id in platform_order_ids
                        ]
                    )
                    orders = await self._with_detail_attribution_signals(
                        access_token,
                        shop,
                        page_orders,
                        force_detail=mode == "backfill",
                    )
                    await self._repository.upsert_page(
                        tenant_id, run_id, shop.id, orders, page.next_page_token
                    )
            return await self._repository.complete_run(
                tenant_id, run_id, committed_at=end
            )
        except Exception as error:
            safe = _sanitize_failure(error, shop.access_token, shop.shop_cipher)
            logger.exception(
                "order_sync_failed",
                exc_info=False,
                extra={
                    "event": "order_sync_failed",
                    "tenant_id": str(tenant_id),
                    "shop_id": str(shop.id),
                    "result": "failed",
                    "error_code": error.code
                    if isinstance(error, TikTokApiError)
                    else type(error).__name__,
                },
            )
            return await self._repository.fail_run(tenant_id, run_id, safe)

    def _resolve_window(
        self,
        *,
        mode: str,
        updated_from: datetime | None,
        updated_to: datetime | None,
        last_success_at: datetime | None,
    ) -> tuple[datetime, datetime]:
        now = datetime.now(UTC)
        if mode == "backfill":
            if updated_from is None or updated_to is None:
                raise OrderSyncWindowError(
                    "Backfill requires both updatedFrom and updatedTo for each approved batch."
                )
            start, end = updated_from, updated_to
            if end <= start:
                raise OrderSyncWindowError("updatedTo must be later than updatedFrom.")
            if end - start > timedelta(days=self._max_backfill_days):
                raise OrderSyncWindowError(
                    f"Backfill windows cannot exceed {self._max_backfill_days} days per batch."
                )
            if last_success_at is None and (
                start
                < now - timedelta(days=self._initial_backfill_days) - _WINDOW_CLOCK_SKEW
                or end < now - timedelta(days=self._initial_backfill_days)
            ):
                raise OrderSyncWindowError(
                    f"The first sync is limited to the most recent {self._initial_backfill_days} days."
                )
            return start, end

        end = updated_to or now
        start = updated_from or (end - timedelta(days=self._initial_backfill_days))
        if last_success_at and updated_from is None:
            start = last_success_at
        if last_success_at is None and (
            start
            < now - timedelta(days=self._initial_backfill_days) - _WINDOW_CLOCK_SKEW
            or end < now - timedelta(days=self._initial_backfill_days)
        ):
            raise OrderSyncWindowError(
                f"The first sync is limited to the most recent {self._initial_backfill_days} days."
            )
        if end <= start:
            raise OrderSyncWindowError("updatedTo must be later than updatedFrom.")
        return start, end

    async def _access_token(self, tenant_id: UUID, shop: AuthorizedOrderShop) -> str:
        if not shop.expires_at or shop.expires_at > datetime.now(UTC) + timedelta(
            seconds=60
        ):
            return shop.access_token
        if not shop.refresh_token:
            raise RuntimeError(
                "TikTok access token is expired and no refresh token is available."
            )
        with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop.id)):
            tokens = await self._client.refresh_access_token(shop.refresh_token)
        if not await self._shop_repository.update_connection_tokens(
            tenant_id, shop.id, tokens
        ):
            raise RuntimeError(
                "TikTok connection could not be updated after token refresh."
            )
        return tokens.access_token

    async def _with_detail_attribution_signals(
        self,
        access_token: str,
        shop: AuthorizedOrderShop,
        orders: list[TikTokOrder],
        *,
        force_detail: bool = False,
    ) -> list[TikTokOrder]:
        """Fetch order details for attribution without enriching ERP read paths."""

        enriched: list[TikTokOrder] = []
        for order in orders:
            if (
                not force_detail
                and self._affiliate_order_client is None
                and (self._ads_order_client is None or not self._ads_access_token)
                and getattr(order, "attribution_signal", None) is not None
                and order.attribution_signal.has_verified_signal
            ):
                enriched.append(
                    replace(
                        order, external_evidence_absence_reason=UNSUPPORTED_ENDPOINT
                    )
                )
                continue
            detail = await self._order_client.get_order(
                access_token,
                shop_cipher=shop.shop_cipher or "",
                order_id=order.platform_order_id,
            )
            if detail.platform_order_id != order.platform_order_id:
                raise TikTokApiError(
                    "TikTok order detail did not match the requested order.",
                    code="order_detail_mismatch",
                    status_code=502,
                )
            affiliate_signal = await self._get_affiliate_signal(
                access_token,
                shop,
                detail,
            )
            ads_signal = await self._get_ads_signal(access_token, shop, detail)
            absence_reason = _external_absence_reason(affiliate_signal, ads_signal)
            enriched.append(
                replace(
                    detail,
                    affiliate_signal=affiliate_signal.signal,
                    ads_signal=ads_signal.signal,
                    external_evidence_absence_reason=absence_reason,
                )
            )
        return enriched

    async def _get_affiliate_signal(
        self,
        access_token: str,
        shop: AuthorizedOrderShop,
        order: TikTokOrder,
    ) -> ExternalOrderEvidenceLookup:
        if self._affiliate_order_client is None:
            return ExternalOrderEvidenceLookup(absence_reason=UNSUPPORTED_ENDPOINT)
        try:
            lookup = getattr(
                self._affiliate_order_client, "lookup_order_evidence", None
            )
            if lookup is not None:
                return await lookup(
                    access_token,
                    shop_cipher=shop.shop_cipher or "",
                    platform_order_id=order.platform_order_id,
                    platform_order_item_ids=tuple(
                        line.platform_line_id for line in order.lines
                    ),
                )
            signal = await self._affiliate_order_client.get_order_signal(
                access_token,
                shop_cipher=shop.shop_cipher or "",
                platform_order_id=order.platform_order_id,
                platform_order_item_ids=tuple(
                    line.platform_line_id for line in order.lines
                ),
            )
            return ExternalOrderEvidenceLookup(signal=signal)
        except (TikTokClientError, ValueError):
            # Affiliate evidence is supplemental; Shop order synchronization must
            # remain successful when the optional scope/endpoint is unavailable.
            return ExternalOrderEvidenceLookup(absence_reason=UNSUPPORTED_ENDPOINT)

    async def _get_ads_signal(
        self, access_token: str, shop: AuthorizedOrderShop, order: TikTokOrder
    ) -> ExternalOrderEvidenceLookup:
        if self._ads_order_client is None or not self._ads_access_token:
            return ExternalOrderEvidenceLookup(absence_reason=UNSUPPORTED_ENDPOINT)
        try:
            lookup = getattr(self._ads_order_client, "lookup_order_evidence", None)
            if lookup is not None:
                return await lookup(
                    self._ads_access_token,
                    shop_cipher=shop.shop_cipher or "",
                    platform_order_id=order.platform_order_id,
                    platform_order_item_ids=tuple(
                        line.platform_line_id for line in order.lines
                    ),
                )
            signal = await self._ads_order_client.get_order_signal(
                self._ads_access_token,
                shop_cipher=shop.shop_cipher or "",
                platform_order_id=order.platform_order_id,
                platform_order_item_ids=tuple(
                    line.platform_line_id for line in order.lines
                ),
            )
            return ExternalOrderEvidenceLookup(signal=signal)
        except (TikTokClientError, ValueError):
            return ExternalOrderEvidenceLookup(absence_reason=UNSUPPORTED_ENDPOINT)


def _external_absence_reason(
    affiliate: ExternalOrderEvidenceLookup,
    ads: ExternalOrderEvidenceLookup,
) -> str | None:
    reasons = {affiliate.absence_reason, ads.absence_reason}
    if PLATFORM_NO_ORDER_LEVEL_EVIDENCE in reasons:
        return PLATFORM_NO_ORDER_LEVEL_EVIDENCE
    if UNSUPPORTED_ENDPOINT in reasons:
        return UNSUPPORTED_ENDPOINT
    return None


def _sanitize_failure(
    error: Exception, access_token: str, shop_cipher: str | None
) -> str:
    message = str(error).splitlines()[0]
    for secret in (access_token, shop_cipher):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = _CREDENTIAL_PATTERN.sub("credential=[REDACTED]", message)
    if isinstance(error, TikTokApiError):
        prefix = f"{type(error).__name__} code={error.code} status={error.status_code}"
    else:
        prefix = type(error).__name__
    return f"{prefix}: {message}"[:1000]


@dataclass(frozen=True)
class AuthorizedOrderShop:
    id: UUID
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    shop_cipher: str | None
