import asyncio
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.parsers.seller_order_export_parser import SellerOrderExportParseError
from backend.app.services.tiktok_seller_export_sync import (
    SELLER_EXPORT_DOWNLOAD_PATH,
    SELLER_EXPORT_PATH,
    SELLER_EXPORT_RECORD_PATH,
    TikTokSellerExportSynchronizer,
    _find_export_record,
    build_seller_export_request,
    seller_api_endpoint,
)
from backend.app.services.tiktok_seller_order_page import ensure_seller_order_page
from erp_api.services.order_evidence_repository import EvidenceIngestResult


def test_export_request_is_bounded_to_merchant_creators_for_28_days() -> None:
    request = build_seller_export_request(
        datetime(2026, 8, 19, 1, tzinfo=UTC),
        lookback_days=28,
    )

    conditions = request["search_condition"]["condition_list"]
    assert conditions["order_source"] == {"value": ["1"]}
    assert conditions["time_order_created"] == {
        "value": ["1784703600000", "1787122799999"]
    }
    assert request["file_type"] == 2
    assert str(request["file_name"]).endswith(".csv")


def test_api_endpoint_removes_stale_dynamic_signatures() -> None:
    source = (
        "https://seller.us.tiktokshopglobalselling.com/api/fulfillment/na/order/list"
        "?oec_seller_id=shop-1&seller_id=seller-1&X-Bogus=old"
        "&X-Gnarly=old&msToken=old&locale=en-US"
    )

    endpoint = seller_api_endpoint(source, SELLER_EXPORT_PATH)
    query = parse_qs(urlsplit(endpoint).query)

    assert urlsplit(endpoint).path == SELLER_EXPORT_PATH
    assert query == {
        "oec_seller_id": ["shop-1"],
        "seller_id": ["seller-1"],
        "locale": ["en-US"],
    }


def test_export_record_is_matched_by_task_id() -> None:
    records = [
        {"export_task_id": "other", "file_key": "other.csv"},
        {"export_task_id": "wanted", "file_key": "wanted.csv"},
    ]

    assert _find_export_record(records, "wanted") == records[1]
    assert _find_export_record(records, "missing") is None


def test_opens_order_page_from_existing_seller_center_session() -> None:
    class LandingPage:
        url = (
            "https://seller.us.tiktokshopglobalselling.com/affiliate/landing"
            "?shop_region=US"
        )

    class OrderPage:
        url = "about:blank"

        def __init__(self) -> None:
            self.visited: list[str] = []

        async def goto(self, url: str, **_kwargs) -> None:
            self.visited.append(url)
            self.url = url

        async def close(self) -> None:
            raise AssertionError("valid order page must remain open")

    class Context:
        def __init__(self) -> None:
            self.pages = [LandingPage()]
            self.opened = OrderPage()

        async def new_page(self) -> OrderPage:
            self.pages.append(self.opened)
            return self.opened

    context = Context()

    selected_context, page = asyncio.run(
        ensure_seller_order_page([context], timeout_seconds=1)
    )

    assert selected_context is context
    assert page is context.opened
    assert page.visited == [
        "https://seller.us.tiktokshopglobalselling.com/order?shop_region=US"
    ]


def test_reuses_seller_page_when_hubstudio_cannot_open_a_new_tab() -> None:
    class LandingPage:
        url = (
            "https://seller.us.tiktokshopglobalselling.com/affiliate/landing"
            "?shop_region=US"
        )

        def __init__(self) -> None:
            self.visited: list[str] = []

        async def goto(self, url: str, **_kwargs) -> None:
            self.visited.append(url)
            self.url = url

    class Context:
        def __init__(self) -> None:
            self.landing = LandingPage()
            self.pages = [self.landing]

        async def new_page(self):
            await asyncio.Event().wait()

    context = Context()

    selected_context, page = asyncio.run(
        ensure_seller_order_page(
            [context],
            timeout_seconds=1,
            page_creation_timeout_seconds=0.001,
        )
    )

    assert selected_context is context
    assert page is context.landing
    assert page.visited == [
        "https://seller.us.tiktokshopglobalselling.com/order?shop_region=US"
    ]


def test_does_not_treat_affiliate_page_as_seller_center_session() -> None:
    class AffiliatePage:
        url = (
            "https://affiliate.tiktokshopglobalselling.com/affiliate/platform/homepage"
            "?shop_region=US&shop_id=platform-shop-1"
        )

    class Context:
        def __init__(self) -> None:
            self.pages = [AffiliatePage()]

        async def new_page(self):
            raise AssertionError("affiliate page must not seed a Seller Center tab")

    with pytest.raises(
        SellerOrderExportParseError,
        match="Seller Center session page is not open",
    ):
        asyncio.run(ensure_seller_order_page([Context()], timeout_seconds=1))


class FakeDownloadResponse:
    status = 200

    async def body(self) -> bytes:
        return b"Order ID,Creator Handle\n941776118773181052,pinky__shop4\n"


class FakeRequestContext:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def get(self, url: str, **_kwargs) -> FakeDownloadResponse:
        self.urls.append(url)
        return FakeDownloadResponse()


class FakePage:
    url = "https://seller.us.tiktokshopglobalselling.com/order"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def evaluate(self, _script: str, argument):
        if isinstance(argument, str):
            return (
                "https://seller.us.tiktokshopglobalselling.com"
                "/api/fulfillment/na/order/list?oec_seller_id=shop-1"
                "&seller_id=seller-1&X-Bogus=stale&msToken=stale"
            )
        path = urlsplit(argument["url"]).path
        body = argument["body"]
        self.calls.append((path, body))
        data = {
            SELLER_EXPORT_PATH: {
                "export_task_id": "task-1",
                "file_key": "pending",
            },
            SELLER_EXPORT_RECORD_PATH: {
                "export_records": [{"export_task_id": "task-1", "file_key": "file-1"}]
            },
            SELLER_EXPORT_DOWNLOAD_PATH: {
                "download_url": (
                    "https://seller.us.tiktokglobalshop.com"
                    "/easesafe/oec_trade_order_export/object/orders.csv?sign=secret"
                )
            },
        }[path]
        return {"status": 200, "payload": {"code": 0, "data": data}}


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.pages = [page]
        self.request = FakeRequestContext()


class FakeRepository:
    def __init__(self) -> None:
        self.shop_id = uuid4()
        self.records = []

    async def resolve_shop_id(self, _tenant_id, platform_shop_id):
        assert platform_shop_id == "shop-1"
        return self.shop_id

    async def ingest_export(self, _tenant_id, shop_id, records):
        assert shop_id == self.shop_id
        self.records = records
        return EvidenceIngestResult(len(records), len(records), 0)


def test_sync_once_creates_downloads_and_ingests_export(capsys) -> None:
    page = FakePage()
    context = FakeContext(page)
    repository = FakeRepository()
    synchronizer = TikTokSellerExportSynchronizer(
        [context],  # type: ignore[list-item]
        repository,  # type: ignore[arg-type]
        uuid4(),
        asyncio.Lock(),
        poll_interval_seconds=0,
    )

    asyncio.run(synchronizer.sync_once())

    assert [path for path, _ in page.calls] == [
        SELLER_EXPORT_PATH,
        SELLER_EXPORT_RECORD_PATH,
        SELLER_EXPORT_DOWNLOAD_PATH,
    ]
    assert page.calls[0][1]["search_condition"]["condition_list"]["order_source"] == {
        "value": ["1"]
    }
    assert repository.records[0]["main_order_id"] == "941776118773181052"
    assert context.request.urls[0].startswith("https://seller.us.tiktokglobalshop.com/")
    output = capsys.readouterr().out
    assert "seller_export_auto_synced" in output
    assert "secret" not in output
