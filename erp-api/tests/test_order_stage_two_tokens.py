"""Token recovery is tested with fake credentials, never real token rotation."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from erp_api.services.order_sync_repository import OrderSyncResult, StoredOrderCursor
from erp_api.services.order_sync_service import AuthorizedOrderShop, OrderSyncService
from erp_api.services.tiktok_order_schemas import TikTokOrderPage


def test_expired_token_refresh_is_persisted_before_use():
    service = object.__new__(OrderSyncService)
    tokens = SimpleNamespace(access_token="new-test-only")
    service._client = SimpleNamespace(refresh_access_token=AsyncMock(return_value=tokens))
    service._shop_repository = SimpleNamespace(update_connection_tokens=AsyncMock(return_value=True))
    tenant_id, shop_id = uuid4(), uuid4()
    shop = AuthorizedOrderShop(shop_id, "old-test-only", "refresh-test-only",
                              datetime.now(UTC) - timedelta(minutes=1), "cipher-test-only")
    assert asyncio.run(service._access_token(tenant_id, shop)) == "new-test-only"
    service._shop_repository.update_connection_tokens.assert_awaited_once_with(tenant_id, shop_id, tokens)


def test_failed_token_persistence_does_not_use_unstored_token():
    service = object.__new__(OrderSyncService)
    service._client = SimpleNamespace(refresh_access_token=AsyncMock(return_value=SimpleNamespace(access_token="new-test-only")))
    service._shop_repository = SimpleNamespace(update_connection_tokens=AsyncMock(return_value=False))
    shop = AuthorizedOrderShop(uuid4(), "old-test-only", "refresh-test-only",
                              datetime.now(UTC) - timedelta(minutes=1), "cipher-test-only")
    with pytest.raises(RuntimeError, match="could not be updated"):
        asyncio.run(service._access_token(uuid4(), shop))


def test_order_failure_does_not_log_tokens_in_exception_traceback(caplog):
    async def pages(*args, **kwargs):
        yield TikTokOrderPage([], "next", 0)
        raise RuntimeError("access-test-secret cipher-test-secret")

    repository = SimpleNamespace(
        get_cursor=AsyncMock(return_value=StoredOrderCursor(None, None, None)),
        create_run=AsyncMock(return_value=uuid4()), upsert_page=AsyncMock(return_value=0),
        fail_run=AsyncMock(return_value=OrderSyncResult(uuid4(), uuid4(), "failed", 0, 0)))
    shops = SimpleNamespace(
        get_authorized_tiktok_shop=AsyncMock(return_value={}),
        get_access_token=AsyncMock(return_value="access-test-secret"),
        get_connection_tokens=AsyncMock(return_value=(None, None, "cipher-test-secret")))
    service = OrderSyncService(repository, SimpleNamespace(), shops, SimpleNamespace(),
                               SimpleNamespace(iter_order_pages=pages))
    with caplog.at_level(logging.ERROR, logger="erp_api.order_sync"):
        asyncio.run(service.sync_orders(uuid4(), shop_id=uuid4()))
    assert "order_sync_failed" in caplog.text
    assert "access-test-secret" not in caplog.text
    assert "cipher-test-secret" not in caplog.text
