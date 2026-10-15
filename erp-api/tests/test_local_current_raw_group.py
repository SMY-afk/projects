from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_application_time_enrichment import (
    SampleApplicationTimeEnrichmentService,
)


@pytest.mark.asyncio
async def test_cancelled_history_is_not_merged_into_a_current_raw_group():
    parent_id = "current"
    parent = SimpleNamespace(
        id=uuid4(),
        platform_application_id=parent_id,
        creator_open_id="creator",
        platform_status="PENDING",
        tiktok_applied_at=None,
        raw_payload={},
        product_id="new",
        product_title="New",
        sku_id="new-sku",
        sku_name="New",
        product_image_urls=["new-image"],
        is_current_projection=True,
    )
    historical = SimpleNamespace(
        id=uuid4(),
        platform_application_id="expired",
        creator_open_id="creator",
        platform_status="OVERDUE_CANCELLED",
        tiktok_applied_at=None,
        raw_payload={
            "original_history": True,
            "ziniao_group_projection": {
                "parent_application_id": parent_id,
                "source_item_ids": [parent_id, "expired"],
            },
        },
        product_id="old",
        product_title="Old",
        sku_id="old-sku",
        sku_name="Old",
        product_image_urls=["old-image"],
        is_current_projection=False,
    )
    events = []

    class Session:
        async def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [parent, historical])

        def add(self, event):
            events.append(event)

        async def commit(self):
            pass

    class Database:
        @asynccontextmanager
        async def system_session_factory(self):
            yield Session()

    group = {
        "id": parent_id,
        "source_item_ids": [parent_id],
        "status": "PENDING",
        "products": [
            {
                "application_id": parent_id,
                "application_time": 1791790200,
                "application_source_type": 1,
                "is_proactive_invitation": True,
                "product": {
                    "id": "new",
                    "title": "New",
                    "sku_id": "new-sku",
                    "sku_name": "New",
                    "sku_image_url": "new-image",
                },
            }
        ],
    }
    await SampleApplicationTimeEnrichmentService(Database()).enrich(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        applications=[group],
        observed_at=datetime(2026, 10, 12, tzinfo=UTC),
        request_id="verified-current-raw",
    )
    assert parent.product_id == "new"
    assert parent.raw_payload["ziniao_group_projection"]["source_item_ids"] == [
        parent_id
    ]
    assert historical.platform_status == "OVERDUE_CANCELLED"
    assert historical.raw_payload["original_history"] is True
    assert "ziniao_group_projection" not in historical.raw_payload
    detached = [
        event
        for event in events
        if event.event_type == "sample_group_projection_detached"
    ]
    assert len(detached) == 1
    assert detached[0].before_data["parent_application_id"] == parent_id
