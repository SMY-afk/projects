from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_application_time_enrichment import (
    SampleApplicationTimeEnrichmentService,
    application_times,
)


class Scalars:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.events = []
        self.commits = 0

    async def scalars(self, _statement):
        return Scalars(self.rows)

    def add(self, event):
        self.events.append(event)

    async def commit(self):
        self.commits += 1


class Database:
    def __init__(self, session) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


def _group(
    application_id: str,
    application_time: int | None,
    *,
    source_type: int | None = 0,
):
    return {
        "products": [
            {
                "application_id": application_id,
                "application_time": application_time,
                "application_source_type": source_type,
                "is_proactive_invitation": (
                    source_type == 1 if source_type is not None else None
                ),
            }
        ]
    }


def test_application_times_keeps_real_values_and_counts_missing() -> None:
    values, missing = application_times(
        (_group("application-1", 1789088309), _group("application-2", None))
    )

    assert values == {"application-1": 1789088309}
    assert missing == 1


@pytest.mark.asyncio
async def test_enrichment_updates_official_record_and_writes_audit_event() -> None:
    application = SimpleNamespace(
        id=uuid4(),
        platform_application_id="application-1",
        creator_open_id="creator-1",
        tiktok_applied_at=None,
        raw_payload={"id": "application-1"},
    )
    session = Session([application])
    service = SampleApplicationTimeEnrichmentService(Database(session))

    result = await service.enrich(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        applications=(_group("application-1", 1789088309),),
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
        request_id="request-1",
    )

    assert result.matched_count == 1
    assert result.updated_count == 1
    assert application.tiktok_applied_at == datetime.fromtimestamp(1789088309, UTC)
    assert application.raw_payload["application_source_type"] == 0
    assert application.raw_payload["is_proactive_invitation"] is False
    assert session.events[0].event_source == "tiktok_ziniao_cdp"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_enrichment_marks_target_collaboration_as_proactive_invitation() -> None:
    application = SimpleNamespace(
        id=uuid4(),
        platform_application_id="application-1",
        tiktok_applied_at=None,
        raw_payload={"id": "application-1"},
    )
    session = Session([application])

    await SampleApplicationTimeEnrichmentService(Database(session)).enrich(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        applications=(_group("application-1", 1789088309, source_type=1),),
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
        request_id="request-1",
    )

    assert application.raw_payload["application_source_type"] == 1
    assert application.raw_payload["is_proactive_invitation"] is True


@pytest.mark.asyncio
async def test_enrichment_projects_one_creator_group_with_all_products() -> None:
    parent = SimpleNamespace(
        id=uuid4(),
        platform_application_id="application-1",
        creator_open_id="creator-1",
        platform_status="PENDING",
        product_id="product-1",
        product_title="Product 1",
        sku_id="sku-1",
        sku_name="Black",
        product_image_urls=[],
        is_current_projection=True,
        tiktok_applied_at=None,
        raw_payload={"id": "application-1"},
    )
    child = SimpleNamespace(
        id=uuid4(),
        platform_application_id="application-2",
        creator_open_id="creator-1",
        platform_status="PENDING",
        product_id="product-2",
        product_title="Product 2",
        sku_id="sku-2",
        sku_name="Pink",
        product_image_urls=[],
        is_current_projection=True,
        tiktok_applied_at=None,
        raw_payload={"id": "application-2"},
    )
    session = Session([parent, child])
    group = {
        "id": "application-1",
        "status": "PENDING",
        "source_item_ids": ["application-1", "application-2"],
        "application_time": 1789088309,
        "products": [
            {
                "application_id": "application-1",
                "application_time": 1789088309,
                "application_source_type": 0,
                "is_proactive_invitation": False,
                "status": "PENDING",
                "product": {
                    "id": "product-1",
                    "title": "Product 1",
                    "sku_id": "sku-1",
                    "sku_name": "Black",
                    "sku_image_url": "https://example.com/one.jpg",
                },
            },
            {
                "application_id": "application-2",
                "application_time": 1789088309,
                "application_source_type": 0,
                "is_proactive_invitation": False,
                "status": "PENDING",
                "product": {"id": "product-2", "title": "Product 2",
                            "sku_id": "sku-2", "sku_name": "Pink"},
            },
        ],
    }

    result = await SampleApplicationTimeEnrichmentService(Database(session)).enrich(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        applications=(group,),
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
        request_id="request-group",
    )

    assert parent.product_id == "product-1、product-2"
    assert parent.sku_id == "sku-1、sku-2"
    assert parent.product_image_urls == [
        "https://example.com/one.jpg",
    ]
    assert parent.is_current_projection is True
    assert child.is_current_projection is False
    assert parent.raw_payload["ziniao_group_projection"]["source_item_ids"] == [
        "application-1",
        "application-2",
    ]
    assert result.application_ids == frozenset({parent.id, child.id})
    assert result.obsolete_platform_application_ids == frozenset({"application-2"})
    assert result.grouped_product_updates == (
        ("application-1", ("product-1", "product-2")),
    )

    repeated = await SampleApplicationTimeEnrichmentService(Database(session)).enrich(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        applications=(group,),
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
        request_id="request-group-repeat",
    )

    assert repeated.updated_count == 0
    assert repeated.application_ids == frozenset({parent.id})
    assert repeated.grouped_product_updates == ()


@pytest.mark.asyncio
async def test_existing_group_ignores_volatile_details_for_same_identity() -> None:
    projection = {
        "parent_application_id": "application-1",
        "source_item_ids": ["application-1"],
        "platform_status": "PENDING",
        "product_id": "product-1",
        "product_title": "Stable title",
        "sku_id": "sku-1",
        "sku_name": "Stable SKU",
        "product_image_urls": ["https://example.com/stable.jpg"],
        "product_ids": ["product-1"],
    }
    parent = SimpleNamespace(
        id=uuid4(),
        platform_application_id="application-1",
        creator_open_id="creator-1",
        platform_status="PENDING",
        product_id="product-1",
        product_title="Stable title",
        sku_id="sku-1",
        sku_name="Stable SKU",
        product_image_urls=["https://example.com/stable.jpg"],
        is_current_projection=True,
        tiktok_applied_at=None,
        raw_payload={"ziniao_group_projection": projection},
    )
    incoming = {
        "id": "application-1",
        "status": "PENDING",
        "source_item_ids": ["application-1"],
        "products": [{"product": {
            "id": "product-1",
            "title": "Volatile title",
            "sku_id": "sku-volatile",
            "sku_name": "Volatile SKU",
            "sku_image_url": "https://example.com/volatile.jpg",
        }}],
    }
    session = Session([parent])

    result = await SampleApplicationTimeEnrichmentService(Database(session)).enrich(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        applications=(incoming,),
        observed_at=datetime(2026, 9, 27, tzinfo=UTC),
        request_id="volatile-group",
    )

    assert result.updated_count == 0
    assert result.grouped_product_updates == ()
    assert parent.raw_payload["ziniao_group_projection"] == projection
    assert not any(e.event_type == "sample_group_projection_reconciled" for e in session.events)
