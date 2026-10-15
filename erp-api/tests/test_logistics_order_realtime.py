from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from erp_api.services.logistics_order_realtime import read_snapshot
from erp_api.services.logistics_order_status_service import LogisticsOrderStatusService


@pytest.mark.asyncio
async def test_official_query_only_caches_tracking_and_reads_background_sync_time():
    tenant, order, shop = uuid4(), uuid4(), uuid4()
    repo = SimpleNamespace(
        get_target=AsyncMock(
            return_value={
                "shop_id": shop,
                "platform_order_id": "100",
                "placed_at": datetime(2026, 10, 7, tzinfo=UTC),
            }
        ),
        get_synced_at=AsyncMock(return_value=datetime(2026, 10, 12, 8, tzinfo=UTC)),
    )
    shops = SimpleNamespace(
        get_access_token=AsyncMock(return_value="test-token"),
        get_shop_cipher=AsyncMock(return_value="test-cipher"),
    )
    detail = SimpleNamespace(
        platform_order_id="100",
        external_status="COMPLETED",
        shipping_type="SELLER",
        platform_updated_at=datetime(2026, 10, 12, tzinfo=UTC),
        fulfillments=[SimpleNamespace(platform_package_id="200")],
    )
    event = SimpleNamespace(
        occurred_at=datetime(2026, 10, 10, tzinfo=UTC),
        action_code="50101",
        sequence_no=1,
        normalized_status="delivered",
        description="Delivered",
    )
    client = SimpleNamespace(
        get_tracking=AsyncMock(return_value=[event]),
        get_package_detail=AsyncMock(
            return_value=SimpleNamespace(
                package_id="200",
                package_status="DELIVERED",
                carrier_name="Carrier",
                tracking_number="1234",
            )
        ),
    )
    service = LogisticsOrderStatusService(
        repo, shops, client, SimpleNamespace(get_order=AsyncMock(return_value=detail))
    )
    service._realtime = SimpleNamespace(
        persist=AsyncMock(return_value=datetime(2026, 10, 12, 8, tzinfo=UTC)),
        save=AsyncMock(),
    )
    result = await service.refresh(tenant, order)
    assert result["deliveredAt"] == event.occurred_at
    assert result["erpSyncedAt"] == datetime(2026, 10, 12, 8, tzinfo=UTC)
    assert result["checkedAt"] != result["erpSyncedAt"]
    assert result["shippingType"] == "SELLER"
    service._realtime.persist.assert_not_awaited()
    repo.get_synced_at.assert_awaited_once_with(tenant, order)
    service._realtime.save.assert_awaited_once_with(tenant, order, result)
    first_checked_at = result["checkedAt"]
    repeated = await service.refresh(tenant, order)
    assert repeated["erpSyncedAt"] == result["erpSyncedAt"]
    assert repeated["checkedAt"] > first_checked_at
    service._realtime.persist.assert_not_awaited()
    client.get_tracking.side_effect = RuntimeError("Official query unavailable")
    service._realtime.persist.reset_mock()
    service._realtime.save.reset_mock()
    with pytest.raises(RuntimeError):
        await service.refresh(tenant, order)
    service._realtime.persist.assert_not_awaited()
    service._realtime.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_page_sync_reports_query_failure_without_claiming_success():
    tenant, order = uuid4(), uuid4()
    service = LogisticsOrderStatusService(None, None, None, None)
    service._realtime = SimpleNamespace(
        sync_shops=AsyncMock(return_value=[{"status": "failed"}]),
        cached=AsyncMock(return_value={}),
    )
    service.list_orders = AsyncMock(return_value={"items": [{"id": order}], "total": 1})
    service.refresh = AsyncMock(side_effect=RuntimeError("Official query unavailable"))
    result = await service.sync_page(tenant, page=1, page_size=20, shop_id=None)
    assert result["refreshFailedCount"] == 1
    assert result["syncResults"] == [{"status": "failed"}]


def test_legacy_snapshot_cannot_keep_incorrect_delivery_or_collection_milestones():
    import json

    result = read_snapshot(
        json.dumps(
            {
                "deliveredAt": "2026-10-08T14:00:00Z",
                "collectedAt": "2026-10-08T14:00:00Z",
                "firstLocationAt": "2026-10-09T14:00:00Z",
                "trackingStatus": "delivered",
            }
        )
    )
    assert result["deliveredAt"] is None and result["collectedAt"] is None
    assert result["firstLocationAt"] == "2026-10-09T14:00:00Z"
    assert result["trackingStatus"] == "pending_recheck"
