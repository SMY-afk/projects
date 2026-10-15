import asyncio
from uuid import uuid4

from backend.app.services.tiktok_affiliate_capture import (
    TARGET_METHOD,
    TARGET_PATH,
    TikTokAffiliateOrderSynchronizer,
)
from erp_api.services.affiliate_sync_repository import AffiliateSyncResult
from erp_api.services.scraped_data_repository import ScrapedDataUpsertResult


def _payload(items: list[object] | None = None) -> dict[str, object]:
    if items is None:
        items = [
            {
                "sku_order_base_info_for_affiliate_seller": {
                    "creator_info": {
                        "creator_id": "creator-1",
                        "creator_nickname": "Creator One",
                    },
                    "product_info": {
                        "product_id": "product-1",
                        "product_name": "Product One",
                    },
                    "sku_order_info": {
                        "campaign_id": "campaign-1",
                        "create_time": 1_789_000_000_000,
                        "main_order_id": "main-1",
                        "sku_id": "sku-1",
                    },
                },
                "sku_order_commission_info_for_affiliate_seller": {},
            }
        ]
    return {
        "code": 0,
        "data": {
            "sku_order_list": items,
            "has_more": True,
            "next_cursor": "sensitive-cursor",
        },
    }


class FakeRequest:
    def __init__(self, method: str = TARGET_METHOD) -> None:
        self.method = method


class FakeResponse:
    def __init__(
        self,
        *,
        url: str = (
            f"https://seller.test{TARGET_PATH}"
            "?oec_seller_id=external-shop&msToken=sensitive-token"
        ),
        method: str = TARGET_METHOD,
        status: int = 200,
        payload: object | None = None,
    ) -> None:
        self.url = url
        self.request = FakeRequest(method)
        self.status = status
        self.payload = _payload() if payload is None else payload

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeRawRepository:
    def __init__(self) -> None:
        self.calls = []

    async def bulk_upsert(self, tenant_id, records):
        self.calls.append((tenant_id, records))
        return ScrapedDataUpsertResult(
            received_count=len(records),
            unique_count=len(records),
            upserted_count=len(records),
        )


class FakeSyncRepository:
    def __init__(self) -> None:
        self.shop_id = uuid4()
        self.resolve_calls = []
        self.upsert_calls = []
        self.failures = []

    async def resolve_shop_id(self, tenant_id, platform_shop_id):
        self.resolve_calls.append((tenant_id, platform_shop_id))
        return self.shop_id

    async def bulk_upsert(
        self,
        tenant_id,
        shop_id,
        records,
        *,
        next_cursor,
        has_more,
    ):
        self.upsert_calls.append((tenant_id, shop_id, records, next_cursor, has_more))
        return AffiliateSyncResult(
            received_count=len(records),
            unique_count=len(records),
            upserted_count=len(records),
        )

    async def mark_failed(self, tenant_id, shop_id, error):
        self.failures.append((tenant_id, shop_id, error))


def _synchronizer():
    raw_repository = FakeRawRepository()
    sync_repository = FakeSyncRepository()
    tenant_id = uuid4()
    synchronizer = TikTokAffiliateOrderSynchronizer(
        raw_repository,  # type: ignore[arg-type]
        sync_repository,  # type: ignore[arg-type]
        tenant_id,
    )
    return synchronizer, raw_repository, sync_repository, tenant_id


def test_affiliate_response_is_normalized_and_bulk_upserted(capsys) -> None:
    synchronizer, raw_repository, sync_repository, tenant_id = _synchronizer()

    asyncio.run(synchronizer.handle_response(FakeResponse()))  # type: ignore[arg-type]

    assert raw_repository.calls[0][0] == tenant_id
    assert raw_repository.calls[0][1][0]["platform_id"] == (
        "affiliate_order:main-1:sku-1"
    )
    call = sync_repository.upsert_calls[0]
    assert call[1] == sync_repository.shop_id
    assert call[2][0]["main_order_id"] == "main-1"
    assert call[3:] == ("sensitive-cursor", True)
    output = capsys.readouterr().out
    assert "affiliate_orders_synced" in output
    assert "sensitive-cursor" not in output
    assert "sensitive-token" not in output


def test_wrong_path_method_or_status_is_not_ingested(capsys) -> None:
    synchronizer, raw_repository, sync_repository, _ = _synchronizer()

    asyncio.run(
        synchronizer.handle_response(FakeResponse(url="https://seller.test/other"))  # type: ignore[arg-type]
    )
    asyncio.run(
        synchronizer.handle_response(FakeResponse(method="GET"))  # type: ignore[arg-type]
    )
    asyncio.run(
        synchronizer.handle_response(FakeResponse(status=503))  # type: ignore[arg-type]
    )

    assert raw_repository.calls == []
    assert sync_repository.upsert_calls == []
    assert len(sync_repository.failures) == 1
    assert "affiliate_sync_failed" in capsys.readouterr().out


def test_invalid_json_marks_shop_sync_failed_without_crashing(capsys) -> None:
    synchronizer, raw_repository, sync_repository, _ = _synchronizer()

    asyncio.run(
        synchronizer.handle_response(FakeResponse(payload=ValueError("invalid")))  # type: ignore[arg-type]
    )

    assert raw_repository.calls == []
    assert sync_repository.upsert_calls == []
    assert len(sync_repository.failures) == 1
    assert "affiliate_sync_failed" in capsys.readouterr().out


def test_empty_page_updates_cursor_state(capsys) -> None:
    synchronizer, raw_repository, sync_repository, _ = _synchronizer()

    asyncio.run(
        synchronizer.handle_response(FakeResponse(payload=_payload([])))  # type: ignore[arg-type]
    )

    assert raw_repository.calls[0][1] == []
    assert sync_repository.upsert_calls[0][2] == []
    assert sync_repository.upsert_calls[0][3:] == ("sensitive-cursor", True)
    assert "affiliate_orders_synced" in capsys.readouterr().out


def test_unknown_shop_is_rejected() -> None:
    synchronizer, raw_repository, sync_repository, _ = _synchronizer()
    sync_repository.resolve_shop_id = lambda *_: _async_none()  # type: ignore[method-assign]

    asyncio.run(synchronizer.handle_response(FakeResponse()))  # type: ignore[arg-type]

    assert raw_repository.calls == []
    assert sync_repository.upsert_calls == []


async def _async_none():
    return None


def test_schedule_response_keeps_task_alive_until_finished() -> None:
    synchronizer, raw_repository, _, _ = _synchronizer()

    async def run() -> None:
        synchronizer.schedule_response(FakeResponse())  # type: ignore[arg-type]
        await synchronizer.wait_for_pending()

    asyncio.run(run())

    assert len(raw_repository.calls) == 1


def test_affiliate_synchronizer_uses_shared_mutation_lock() -> None:
    raw_repository = FakeRawRepository()
    sync_repository = FakeSyncRepository()

    async def build_and_check() -> None:
        shared_lock = asyncio.Lock()
        synchronizer = TikTokAffiliateOrderSynchronizer(
            raw_repository,  # type: ignore[arg-type]
            sync_repository,  # type: ignore[arg-type]
            uuid4(),
            mutation_lock=shared_lock,
        )
        assert synchronizer._upsert_lock is shared_lock

    asyncio.run(build_and_check())
