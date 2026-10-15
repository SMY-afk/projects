from __future__ import annotations

from uuid import UUID

from erp_api.services.returns_domain import ReturnValidationError
from erp_api.services.returns_sync_repository import ReturnsSyncRepository
from erp_api.services.shop_repository import ShopRepository
from erp_api.services.tiktok_return_client import HttpTikTokReturnClient


class ReturnsSyncService:
    def __init__(
        self,
        shop_repository: ShopRepository,
        client: HttpTikTokReturnClient,
        sync_repository: ReturnsSyncRepository,
    ) -> None:
        self._shop_repository = shop_repository
        self._client = client
        self._sync_repository = sync_repository

    async def sync(self, tenant_id: UUID, *, shop_id: UUID) -> dict[str, object]:
        access_token = await self._shop_repository.get_access_token(tenant_id, shop_id)
        shop_cipher = await self._shop_repository.get_shop_cipher(tenant_id, shop_id)
        if not access_token or not shop_cipher:
            raise ReturnValidationError(
                "The selected TikTok shop is not authorized for return synchronization."
            )
        fetched = upserted = unmatched_orders = unmatched_lines = 0
        async for page in self._client.iter_returns(
            access_token,
            shop_cipher=shop_cipher,
            page_size=20,
            tenant_id=str(tenant_id),
            shop_id=str(shop_id),
        ):
            result = await self._sync_repository.upsert_page(
                tenant_id, shop_id, page.returns
            )
            fetched += result.fetched_count
            upserted += result.upserted_count
            unmatched_orders += result.unmatched_order_count
            unmatched_lines += result.unmatched_line_count
        return {
            "shopId": shop_id,
            "fetchedCount": fetched,
            "upsertedCount": upserted,
            "unmatchedOrderCount": unmatched_orders,
            "unmatchedLineCount": unmatched_lines,
        }
