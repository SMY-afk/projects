import asyncio
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.returns_sync_service import ReturnsSyncService


class FakeShopRepository:
    async def get_access_token(self, tenant_id, shop_id):
        return "access-token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "shop-cipher"


class FakeClient:
    async def iter_returns(self, access_token, **kwargs):
        assert access_token == "access-token"
        assert kwargs["shop_cipher"] == "shop-cipher"
        yield SimpleNamespace(returns=["one", "two"], next_page_token="", total_count=2)


class FakeSyncRepository:
    async def upsert_page(self, tenant_id, shop_id, records):
        assert records == ["one", "two"]
        return SimpleNamespace(
            fetched_count=2,
            upserted_count=1,
            unmatched_order_count=1,
            unmatched_line_count=0,
        )


def test_sync_accumulates_real_platform_match_results() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    service = ReturnsSyncService(
        FakeShopRepository(), FakeClient(), FakeSyncRepository()
    )

    result = asyncio.run(service.sync(tenant_id, shop_id=shop_id))

    assert result == {
        "shopId": shop_id,
        "fetchedCount": 2,
        "upsertedCount": 1,
        "unmatchedOrderCount": 1,
        "unmatchedLineCount": 0,
    }
