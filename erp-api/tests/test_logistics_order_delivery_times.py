from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from erp_api.services.logistics_order_delivery_times import delivered_times


@pytest.mark.asyncio
async def test_old_normalized_warehouse_event_is_not_a_delivery_timestamp():
    order = uuid4()
    prepared = datetime(2026, 10, 8, tzinfo=UTC)
    delivered = prepared + timedelta(days=3)
    results = [SimpleNamespace(all=lambda: []), SimpleNamespace(all=lambda: [
        (order, prepared, 'tiktok:pkg:500901:123:1', 'Package is being prepared at warehouse.'),
        (order, delivered, 'tiktok:pkg:50101:456:2', 'Delivered, Front Door/Porch'),
    ])]
    session = SimpleNamespace(execute=AsyncMock(side_effect=results))
    assert await delivered_times(session, uuid4(), [order]) == {order: delivered}
