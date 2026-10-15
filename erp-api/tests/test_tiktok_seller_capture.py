import asyncio
from uuid import uuid4

from backend.app.services.tiktok_seller_capture import (
    RAW_ONLY_PATHS,
    SELLER_EXPORT_DOWNLOAD_PATH,
    SELLER_EXPORT_FILE_PREFIX,
    SELLER_ORDER_PATH,
    SELLER_PRODUCT_LIST_PATH,
    SELLER_VIDEO_COMPLETION_PATH,
    TikTokSellerCenterSynchronizer,
)
from erp_api.services.order_evidence_repository import EvidenceIngestResult
from erp_api.services.scraped_data_repository import ScrapedDataUpsertResult


class FakeRequest:
    method = "POST"

    def __init__(self, url="https://seller.test/order"):
        self.url = url


class FakePage:
    def __init__(self):
        self.evaluate_calls = []

    async def evaluate(self, script, arguments):
        self.evaluate_calls.append((script, arguments))
        return 200


class FakeFrame:
    def __init__(self, page):
        self.page = page


class FakeRouteResponse:
    status = 200

    def __init__(self, body):
        self._body = body

    async def body(self):
        return self._body


class FakeRoute:
    def __init__(self, url, body):
        self.request = FakeRequest(url)
        self._response = FakeRouteResponse(body)
        self.fulfilled = False
        self.continued = False

    async def fetch(self):
        return self._response

    async def fulfill(self, **_kwargs):
        self.fulfilled = True

    async def continue_(self):
        self.continued = True


class FakeResponse:
    def __init__(self, path, payload=None, *, url=None):
        self.url = (
            url or f"https://seller.test{path}?oec_seller_id=shop-1&msToken=secret"
        )
        self.status = 200
        self.request = FakeRequest()
        self._payload = payload
        self.page = FakePage()
        self.frame = FakeFrame(self.page)

    async def json(self):
        return self._payload


class FakeRawRepository:
    def __init__(self):
        self.calls = []

    async def bulk_upsert(self, tenant_id, records):
        self.calls.append((tenant_id, records))
        return ScrapedDataUpsertResult(len(records), len(records), len(records))


class FakeSyncRepository:
    def __init__(self):
        self.shop_id = uuid4()
        self.calls = []
        self.export_calls = []

    async def resolve_shop_id(self, tenant_id, platform_shop_id):
        return self.shop_id

    async def ingest_orders(self, tenant_id, shop_id, records):
        self.calls.append((tenant_id, shop_id, records))
        return EvidenceIngestResult(len(records), 1, 0)

    async def ingest_export(self, tenant_id, shop_id, records):
        self.export_calls.append((tenant_id, shop_id, records))
        return EvidenceIngestResult(len(records), 1, 0)


def _synchronizer(*, enable_product_fallback: bool = False):
    raw = FakeRawRepository()
    sync = FakeSyncRepository()
    synchronizer = TikTokSellerCenterSynchronizer(
        raw,  # type: ignore[arg-type]
        sync,  # type: ignore[arg-type]
        uuid4(),
        enable_product_fallback=enable_product_fallback,
    )
    return synchronizer, raw, sync


def test_seller_orders_create_evidence_without_retaining_buyer_payload() -> None:
    synchronizer, raw, sync = _synchronizer()
    payload = {
        "code": 0,
        "data": {
            "main_orders": [
                {
                    "main_order_id": "order-1",
                    "sku_module": [
                        {
                            "order_line_ids": ["line-1"],
                            "product_id": "product-1",
                            "sku_id": "sku-1",
                        }
                    ],
                    "buyer_info_module": {"shipping_address": {"name": "PII"}},
                }
            ]
        },
    }

    asyncio.run(
        synchronizer.handle_response(FakeResponse(SELLER_ORDER_PATH, payload))  # type: ignore[arg-type]
    )

    assert len(sync.calls) == 1
    assert raw.calls == []
    assert "buyer_info_module" not in str(sync.calls)


def test_product_live_and_creator_payloads_are_raw_only() -> None:
    synchronizer, raw, sync = _synchronizer()
    aggregate_paths = {
        path: data_type
        for path, data_type in RAW_ONLY_PATHS.items()
        if path != SELLER_VIDEO_COMPLETION_PATH
    }

    for path in aggregate_paths:
        asyncio.run(
            synchronizer.handle_response(
                FakeResponse(path, {"code": 0, "data": {"items": []}})  # type: ignore[arg-type]
            )
        )

    assert len(raw.calls) == len(aggregate_paths)
    assert sync.calls == []
    assert {call[1][0]["data_type"] for call in raw.calls} == set(
        aggregate_paths.values()
    )


def test_product_catalog_requests_complete_active_product_page() -> None:
    synchronizer, raw, sync = _synchronizer(enable_product_fallback=True)
    payload = {
        "code": 0,
        "data": {
            "page_number": 1,
            "page_size": 50,
            "total_product_count": 14,
            "products": [],
        },
    }
    response = FakeResponse(
        SELLER_PRODUCT_LIST_PATH,
        payload,
        url=(
            "https://seller.test/api/v1/product/local/products/list"
            "?oec_seller_id=shop-1&tab_id=2&page_number=1&page_size=50"
        ),
    )

    asyncio.run(synchronizer.handle_response(response))  # type: ignore[arg-type]

    assert raw.calls[0][1][0]["data_type"] == "seller_product_catalog"
    assert response.page.evaluate_calls[0][1]["tabId"] == "1"
    assert response.page.evaluate_calls[0][1]["pageNumber"] == 1
    assert response.page.evaluate_calls[0][1]["pageSize"] == 100
    assert sync.calls == []


def test_product_catalog_is_ignored_without_emergency_fallback() -> None:
    synchronizer, raw, sync = _synchronizer()

    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(
                SELLER_PRODUCT_LIST_PATH,
                {"code": 0, "data": {"products": []}},
            )  # type: ignore[arg-type]
        )
    )

    assert raw.calls == []
    assert sync.calls == []


def test_self_operated_video_metrics_never_create_order_evidence() -> None:
    synchronizer, raw, sync = _synchronizer()
    video_path = next(
        path
        for path, data_type in RAW_ONLY_PATHS.items()
        if data_type == "seller_video_analytics"
    )
    payload = {
        "code": 0,
        "data": {
            "segments": [
                {
                    "timed_lists": [
                        {
                            "stats": [
                                {
                                    "video_meta": {"id": "video-1"},
                                    "sku_order_cnt": 7,
                                    "sub_order_cnt": 7,
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }

    response = FakeResponse(video_path, payload)
    asyncio.run(synchronizer.handle_response(response))  # type: ignore[arg-type]

    assert len(raw.calls) == 1
    assert raw.calls[0][1][0]["data_type"] == "seller_video_analytics"
    assert raw.calls[0][1][0]["raw_data"] == payload
    assert response.page.evaluate_calls[0][1]["videoId"] == "video-1"
    assert response.page.evaluate_calls[0][1]["path"] == SELLER_VIDEO_COMPLETION_PATH
    assert sync.calls == []


def test_video_completion_is_retained_without_order_evidence() -> None:
    synchronizer, raw, sync = _synchronizer()
    payload = {
        "code": 0,
        "data": {
            "segments": [
                {
                    "item_id": "video-1",
                    "data_list": [
                        {
                            "indicator_type": 1,
                            "trend_data": [
                                {
                                    "base_time": 8,
                                    "value": {
                                        "base_indicator_value": {
                                            "decimal_value": "0.125",
                                            "formatted_value": "12.50%",
                                        }
                                    },
                                },
                                {
                                    "base_time": 9,
                                    "value": {
                                        "base_indicator_value": {
                                            "decimal_value": "0",
                                            "formatted_value": "0.00%",
                                        }
                                    },
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    }

    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(SELLER_VIDEO_COMPLETION_PATH, payload)  # type: ignore[arg-type]
        )
    )

    assert raw.calls[0][1][0]["data_type"] == "seller_video_completion"
    assert raw.calls[0][1][0]["raw_data"]["completion_rate"] == "0.125"
    assert sync.calls == []


def test_seller_synchronizer_uses_shared_mutation_lock() -> None:
    raw = FakeRawRepository()
    sync = FakeSyncRepository()

    async def build_and_check() -> None:
        shared_lock = asyncio.Lock()
        synchronizer = TikTokSellerCenterSynchronizer(
            raw,  # type: ignore[arg-type]
            sync,  # type: ignore[arg-type]
            uuid4(),
            mutation_lock=shared_lock,
        )
        assert synchronizer._lock is shared_lock

    asyncio.run(build_and_check())


def test_downloaded_export_creates_exact_creator_evidence_without_raw_csv(
    tmp_path,
) -> None:
    synchronizer, raw, sync = _synchronizer()
    download_url = (
        "https://seller.us.tiktokglobalshop.com"
        f"{SELLER_EXPORT_FILE_PREFIX}safe-file.csv?signature=secret"
    )
    csv_body = (
        b"Order ID,Buyer Name,Creator Handle\n"
        b"941776118773181052\t,Private Buyer,pinky__shop4\n"
    )
    export_path = tmp_path / "orders.csv"
    export_path.write_bytes(csv_body)

    asyncio.run(
        synchronizer.handle_response(
            FakeResponse(
                SELLER_EXPORT_DOWNLOAD_PATH,
                {"code": 0, "data": {"download_url": download_url}},
            )  # type: ignore[arg-type]
        )
    )
    route = FakeRoute(download_url, export_path.read_bytes())
    asyncio.run(synchronizer.handle_export_route(route))  # type: ignore[arg-type]

    assert len(sync.export_calls) == 1
    assert route.fulfilled is True
    record = sync.export_calls[0][2][0]
    assert record["main_order_id"] == "941776118773181052"
    assert record["evidence_json"]["creator_handle"] == "pinky__shop4"
    assert "Private Buyer" not in str(sync.export_calls)
    assert raw.calls == []
