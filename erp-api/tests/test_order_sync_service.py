import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from erp_api.services import order_sync_service as order_sync_module
from erp_api.services.external_order_evidence import UNSUPPORTED_ENDPOINT
from erp_api.services.order_sync_repository import OrderSyncResult, StoredOrderCursor
from erp_api.services.order_sync_service import OrderSyncService, OrderSyncWindowError
from erp_api.services.tiktok_affiliate_order_schemas import TikTokAffiliateOrderSignal
from erp_api.services.tiktok_order_schemas import (
    TikTokOrder,
    TikTokOrderAttributionSignal,
    TikTokOrderPage,
)
from erp_api.services.tiktok_transport import TikTokApiError


class FakeShopRepository:
    async def get_authorized_tiktok_shop(self, tenant_id, shop_id):
        return {"id": shop_id}

    async def get_access_token(self, tenant_id, shop_id):
        return "access-token"

    async def get_connection_tokens(self, tenant_id, shop_id):
        return None, None, "shop-cipher"


class FakeSyncRepository:
    def __init__(self):
        self.pages = []
        self.orders = []
        self.committed = False

    async def get_cursor(self, tenant_id, shop_id):
        return StoredOrderCursor(None, None, None)

    async def create_run(self, tenant_id, shop_id, **kwargs):
        return uuid4()

    async def upsert_page(self, tenant_id, run_id, shop_id, orders, next_cursor):
        self.pages.append(next_cursor)
        self.orders.append(orders)
        return len(orders)

    async def complete_run(self, tenant_id, run_id, committed_at):
        self.committed = True
        return OrderSyncResult(run_id, uuid4(), "succeeded", 0, 0)

    async def fail_run(self, tenant_id, run_id, error):
        return OrderSyncResult(
            run_id,
            uuid4(),
            "failed",
            0,
            0,
            recovery_cursor=self.pages[-1] if self.pages else None,
            error=error,
        )


class FakeOrderClient:
    def __init__(self, fail=False, orders=None, details=None):
        self.fail = fail
        self.orders = orders or []
        self.details = details or {}
        self.detail_requests = []
        self.page_windows = []

    async def iter_order_pages(self, *args, **kwargs):
        self.page_windows.append((kwargs["updated_from"], kwargs["updated_to"]))
        yield TikTokOrderPage(self.orders, "page-2", len(self.orders))
        if self.fail:
            raise RuntimeError("page failed")
        yield TikTokOrderPage([], "", 0)

    async def get_order(self, access_token, *, shop_cipher, order_id):
        self.detail_requests.append((access_token, shop_cipher, order_id))
        return self.details[order_id]


def _service(repository, order_client):
    return OrderSyncService(
        repository,
        SimpleNamespace(),
        FakeShopRepository(),
        SimpleNamespace(),
        order_client,
        initial_backfill_days=30,
    )


def test_sync_commits_cursor_only_after_every_page_succeeds() -> None:
    repository = FakeSyncRepository()

    result = asyncio.run(
        _service(repository, FakeOrderClient()).sync_orders(uuid4(), shop_id=uuid4())
    )

    assert result.status == "succeeded"
    assert repository.pages == ["page-2", ""]
    assert repository.committed is True


def test_backfill_requires_an_explicit_window() -> None:
    with pytest.raises(OrderSyncWindowError, match="both updatedFrom and updatedTo"):
        asyncio.run(
            _service(FakeSyncRepository(), FakeOrderClient()).sync_orders(
                uuid4(), shop_id=uuid4(), mode="backfill"
            )
        )


def test_first_backfill_rejects_a_window_older_than_thirty_days() -> None:
    now = datetime.now(UTC)
    with pytest.raises(OrderSyncWindowError, match="most recent 30 days"):
        asyncio.run(
            _service(FakeSyncRepository(), FakeOrderClient()).sync_orders(
                uuid4(),
                shop_id=uuid4(),
                mode="backfill",
                updated_from=now - timedelta(days=31),
                updated_to=now - timedelta(days=30, minutes=1),
            )
        )


def test_first_incremental_rejects_an_explicit_older_window() -> None:
    now = datetime.now(UTC)
    with pytest.raises(OrderSyncWindowError, match="most recent 30 days"):
        asyncio.run(
            _service(FakeSyncRepository(), FakeOrderClient()).sync_orders(
                uuid4(),
                shop_id=uuid4(),
                mode="incremental",
                updated_from=now - timedelta(days=31),
                updated_to=now,
            )
        )


def test_approved_older_backfill_window_is_allowed_after_first_success() -> None:
    service = _service(FakeSyncRepository(), FakeOrderClient())
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)

    resolved = service._resolve_window(
        mode="backfill",
        updated_from=start,
        updated_to=end,
        last_success_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert resolved == (start, end)


def test_backfill_window_is_limited_to_one_batch_of_thirty_days() -> None:
    service = _service(FakeSyncRepository(), FakeOrderClient())
    now = datetime.now(UTC)

    with pytest.raises(OrderSyncWindowError, match="cannot exceed 30 days"):
        service._resolve_window(
            mode="backfill",
            updated_from=now - timedelta(days=31),
            updated_to=now,
            last_success_at=now,
        )


def test_sync_failure_keeps_recovery_cursor_without_committing() -> None:
    repository = FakeSyncRepository()

    result = asyncio.run(
        _service(repository, FakeOrderClient(fail=True)).sync_orders(
            uuid4(), shop_id=uuid4()
        )
    )

    assert result.status == "failed"
    assert result.recovery_cursor == "page-2"
    assert repository.committed is False


def _order(order_id: str, *, signal: bool | None) -> TikTokOrder:
    updated_at = datetime(2026, 8, 13, tzinfo=UTC)
    return TikTokOrder(
        platform_order_id=order_id,
        order_number=order_id,
        status="completed",
        external_status="COMPLETED",
        currency="USD",
        subtotal_amount_minor=0,
        shipping_fee_minor=0,
        discount_amount_minor=0,
        tax_amount_minor=0,
        total_amount_minor=0,
        buyer_username=None,
        placed_at=updated_at,
        paid_at=updated_at,
        platform_updated_at=updated_at,
        lines=[],
        fulfillments=[],
        recipient=None,
        attribution_signal=TikTokOrderAttributionSignal(
            is_sample_order=signal,
            source_updated_at=updated_at,
        ),
    )


def test_sync_enriches_only_missing_page_attribution_signals_from_order_detail() -> (
    None
):
    repository = FakeSyncRepository()
    missing = _order("missing", signal=None)
    present = _order("present", signal=False)
    enriched = _order("missing", signal=True)
    client = FakeOrderClient(orders=[missing, present], details={"missing": enriched})

    result = asyncio.run(
        _service(repository, client).sync_orders(uuid4(), shop_id=uuid4())
    )

    assert result.status == "succeeded"
    assert client.detail_requests == [("access-token", "shop-cipher", "missing")]
    assert repository.pages == ["page-2", ""]
    assert repository.orders[0][0].attribution_signal.is_sample_order is True
    assert repository.orders[0][1].attribution_signal.is_sample_order is False


def test_sync_does_not_fetch_order_detail_when_page_has_verified_signal() -> None:
    repository = FakeSyncRepository()
    client = FakeOrderClient(orders=[_order("present", signal=False)])

    result = asyncio.run(
        _service(repository, client).sync_orders(uuid4(), shop_id=uuid4())
    )

    assert result.status == "succeeded"
    assert client.detail_requests == []


class FakeAffiliateClient:
    def __init__(self, signal=None, error=None):
        self.signal = signal
        self.error = error
        self.requests = []

    async def get_order_signal(
        self, access_token, *, shop_cipher, platform_order_id, platform_order_item_ids
    ):
        self.requests.append(
            (access_token, shop_cipher, platform_order_id, platform_order_item_ids)
        )
        if self.error:
            raise self.error
        return self.signal


def test_configured_affiliate_client_fetches_details_even_when_page_signal_exists() -> (
    None
):
    repository = FakeSyncRepository()
    order = _order("present", signal=False)
    detail = _order("present", signal=False)
    affiliate = FakeAffiliateClient(
        TikTokAffiliateOrderSignal(
            external_conversion_id="conversion-1",
            match_key_type="order_id",
            match_key="present",
            creator_external_id="creator-1",
            traffic_source="organic",
            entry_point="video",
        )
    )
    client = FakeOrderClient(orders=[order], details={"present": detail})
    service = OrderSyncService(
        repository,
        SimpleNamespace(),
        FakeShopRepository(),
        SimpleNamespace(),
        client,
        affiliate_order_client=affiliate,
    )

    result = asyncio.run(service.sync_orders(uuid4(), shop_id=uuid4()))

    assert result.status == "succeeded"
    assert client.detail_requests == [("access-token", "shop-cipher", "present")]
    assert affiliate.requests[0][2] == "present"
    assert (
        repository.orders[0][0].affiliate_signal.external_conversion_id
        == "conversion-1"
    )


def test_affiliate_endpoint_failure_does_not_fail_shop_order_sync() -> None:
    repository = FakeSyncRepository()
    order = _order("present", signal=False)
    client = FakeOrderClient(orders=[order], details={"present": order})
    affiliate = FakeAffiliateClient(
        error=TikTokApiError(
            "optional endpoint unavailable",
            code="affiliate_unavailable",
            status_code=403,
        )
    )
    service = OrderSyncService(
        repository,
        SimpleNamespace(),
        FakeShopRepository(),
        SimpleNamespace(),
        client,
        affiliate_order_client=affiliate,
    )

    result = asyncio.run(service.sync_orders(uuid4(), shop_id=uuid4()))

    assert result.status == "succeeded"
    assert repository.orders[0][0].affiliate_signal is None


def test_missing_source_field_is_persisted_as_unknown_without_failing_batch() -> None:
    repository = FakeSyncRepository()
    missing_source = _order("missing-source", signal=None)
    client = FakeOrderClient(
        orders=[missing_source], details={"missing-source": missing_source}
    )

    result = asyncio.run(
        _service(repository, client).sync_orders(uuid4(), shop_id=uuid4())
    )

    assert result.status == "succeeded"
    assert repository.orders[0][0].attribution_signal is not None
    assert repository.orders[0][0].attribution_signal.is_sample_order is None


def test_unconfigured_external_evidence_is_recorded_as_unsupported() -> None:
    repository = FakeSyncRepository()
    order = _order("missing-external-evidence", signal=False)
    client = FakeOrderClient(
        orders=[order], details={"missing-external-evidence": order}
    )

    result = asyncio.run(
        _service(repository, client).sync_orders(uuid4(), shop_id=uuid4())
    )

    assert result.status == "succeeded"
    assert (
        repository.orders[0][0].external_evidence_absence_reason == UNSUPPORTED_ENDPOINT
    )


def test_backfill_fetches_every_order_detail_to_reclassify_the_window() -> None:
    repository = FakeSyncRepository()
    first = _order("first", signal=False)
    second = _order("second", signal=True)
    first_detail = _order("first", signal=True)
    second_detail = _order("second", signal=False)
    client = FakeOrderClient(
        orders=[first, second],
        details={"first": first_detail, "second": second_detail},
    )
    updated_to = datetime.now(UTC) - timedelta(days=1)
    updated_from = updated_to - timedelta(days=1)

    result = asyncio.run(
        _service(repository, client).sync_orders(
            uuid4(),
            shop_id=uuid4(),
            mode="backfill",
            updated_from=updated_from,
            updated_to=updated_to,
        )
    )

    assert result.status == "succeeded"
    assert client.page_windows[0] == (updated_from, updated_to)
    assert client.detail_requests == [
        ("access-token", "shop-cipher", "first"),
        ("access-token", "shop-cipher", "second"),
    ]
    assert repository.orders[0][0].attribution_signal.is_sample_order is True
    assert repository.orders[0][1].attribution_signal.is_sample_order is False


def test_targeted_backfill_fetches_details_only_for_requested_platform_orders() -> None:
    repository = FakeSyncRepository()
    first = _order("first", signal=False)
    second = _order("second", signal=False)
    client = FakeOrderClient(
        orders=[first, second],
        details={"second": _order("second", signal=True)},
    )

    updated_to = datetime.now(UTC) - timedelta(days=1)
    updated_from = updated_to - timedelta(days=1)
    result = asyncio.run(
        _service(repository, client).sync_orders(
            uuid4(),
            shop_id=uuid4(),
            mode="backfill",
            updated_from=updated_from,
            updated_to=updated_to,
            platform_order_ids={"second"},
        )
    )

    assert result.status == "succeeded"
    assert client.detail_requests == [("access-token", "shop-cipher", "second")]
    assert [order.platform_order_id for order in repository.orders[0]] == ["second"]


def test_sync_rejects_order_detail_for_a_different_order_id(monkeypatch) -> None:
    repository = FakeSyncRepository()
    client = FakeOrderClient(
        orders=[_order("requested", signal=None)],
        details={"requested": _order("returned", signal=True)},
    )

    log_exception = Mock()
    monkeypatch.setattr(order_sync_module.logger, "exception", log_exception)
    result = asyncio.run(
        _service(repository, client).sync_orders(uuid4(), shop_id=uuid4())
    )

    assert result.status == "failed"
    assert result.error and "order_detail_mismatch" in result.error
    assert repository.pages == []
    log_exception.assert_called_once()
    assert log_exception.call_args.args[0] == "order_sync_failed"
