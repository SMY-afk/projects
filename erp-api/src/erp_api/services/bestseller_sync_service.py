from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from erp_api.services.bestseller_repository import (
    BestsellerRepository,
    BestsellerSnapshotQuery,
)
from erp_api.services.shop_repository import ShopRepository
from erp_api.services.tiktok_bestseller_client import (
    BestsellerAuthorType,
    BestsellerTimeSlot,
    TikTokBestsellerClient,
)
from erp_api.services.tiktok_bestseller_schemas import (
    BestsellerCurrency,
    BestsellerEntityType,
    TikTokBestsellerPage,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRateLimitError,
    TikTokTimeoutError,
    tiktok_request_context,
)


@dataclass(frozen=True)
class BestsellerSyncResult:
    snapshot_id: UUID
    entry_count: int
    platform_request_id: str


class BestsellerSyncError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        retryable: bool,
        retry_after_seconds: float | None = None,
        snapshot_marked_stale: bool = False,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.snapshot_marked_stale = snapshot_marked_stale


class BestsellerSyncService:
    def __init__(
        self,
        repository: BestsellerRepository,
        shop_repository: ShopRepository,
        client: TikTokBestsellerClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._shop_repository = shop_repository
        self._client = client
        self._clock = clock

    async def sync(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        entity_type: BestsellerEntityType,
        reference_date: date,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
        author_type: BestsellerAuthorType | None = None,
    ) -> BestsellerSyncResult:
        shop, access_token, shop_cipher = await asyncio.gather(
            self._shop_repository.get_authorized_tiktok_shop(tenant_id, shop_id),
            self._shop_repository.get_access_token(tenant_id, shop_id),
            self._shop_repository.get_shop_cipher(tenant_id, shop_id),
        )
        if shop is None or not access_token or not shop_cipher:
            raise RuntimeError("Bestseller sync requires authorized shop credentials.")
        timezone = shop.get("timezone")
        if not isinstance(timezone, str) or not timezone:
            raise RuntimeError("Bestseller sync requires a shop timezone.")
        latest_completed = self._latest_completed_date(timezone)
        if reference_date > latest_completed:
            raise ValueError(
                "reference_date must be a completed shop-local calendar date."
            )

        query = BestsellerSnapshotQuery(
            shop_id=shop_id,
            entity_type=entity_type,
            reference_date=reference_date,
            time_slot=time_slot,
            currency=currency,
            author_type=author_type,
        )

        try:
            with tiktok_request_context(
                tenant_id=str(tenant_id),
                shop_id=str(shop_id),
            ):
                page = await self._fetch(
                    entity_type,
                    access_token,
                    shop_cipher=shop_cipher,
                    reference_date=reference_date,
                    time_slot=time_slot,
                    currency=currency,
                    author_type=author_type,
                )
        except TikTokRateLimitError as error:
            await self._raise_sync_error(
                tenant_id,
                query,
                error,
                category="rate_limited",
                retryable=True,
                retry_after_seconds=error.retry_after_seconds,
            )
        except TikTokApiError as error:
            category = (
                "reauthorization_required"
                if error.code == "105005"
                else "platform_error"
            )
            await self._raise_sync_error(
                tenant_id,
                query,
                error,
                category=category,
                retryable=False,
            )
        except TikTokTimeoutError as error:
            await self._raise_sync_error(
                tenant_id,
                query,
                error,
                category="timeout",
                retryable=True,
            )
        snapshot_id = await self._repository.replace_snapshot(
            tenant_id,
            query,
            page,
        )
        return BestsellerSyncResult(
            snapshot_id=snapshot_id,
            entry_count=len(page.entries),
            platform_request_id=page.platform_request_id or "",
        )

    async def _raise_sync_error(
        self,
        tenant_id: UUID,
        query: BestsellerSnapshotQuery,
        error: Exception,
        *,
        category: str,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        marked = await self._repository.mark_snapshot_stale(
            tenant_id,
            query,
            category,
        )
        raise BestsellerSyncError(
            str(error),
            category=category,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            snapshot_marked_stale=marked,
        ) from error

    async def _fetch(
        self,
        entity_type: BestsellerEntityType,
        access_token: str,
        *,
        shop_cipher: str,
        reference_date: date,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
        author_type: BestsellerAuthorType | None,
    ) -> TikTokBestsellerPage:
        common = {
            "shop_cipher": shop_cipher,
            "date": reference_date.isoformat(),
            "time_slot": time_slot,
            "currency": currency,
        }
        if entity_type == "creator":
            if author_type is None:
                raise ValueError("Creator sync requires author_type.")
            return await self._client.list_creators(
                access_token,
                **common,
                author_type=author_type,
            )
        methods = {
            "product": self._client.list_products,
            "video": self._client.list_videos,
            "live": self._client.list_lives,
        }
        try:
            method = methods[entity_type]
        except KeyError as error:
            raise ValueError("entity_type is invalid.") from error
        if author_type is not None:
            raise ValueError("author_type is only valid for creator sync.")
        return await method(access_token, **common)

    def _latest_completed_date(self, timezone: str) -> date:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Bestseller sync clock must include a UTC offset.")
        return now.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)
