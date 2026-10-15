from uuid import uuid4

import pytest

from erp_api.services.sample_notification_products import (
    list_notification_product_image_urls,
)


class FakeSession:
    def __init__(self, rows=()) -> None:
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self

    def all(self):
        return self.rows


@pytest.mark.asyncio
async def test_lists_distinct_images_for_triple_checked_current_applications() -> None:
    session = FakeSession(
        (
            ("https://cdn.example/product-1.jpg",),
            ("https://cdn.example/product-2.jpg",),
            ("https://cdn.example/product-1.jpg",),
        )
    )

    urls = await list_notification_product_image_urls(
        session,
        tenant_id=uuid4(),
        shop_id=uuid4(),
        application_id=uuid4(),
        platform_status="PENDING",
        creator_open_id="creator-1",
        creator_username=" Creator_Name ",
        fallback_image_url=None,
    )

    assert urls == (
        "https://cdn.example/product-1.jpg",
        "https://cdn.example/product-2.jpg",
    )
    sql = str(session.statements[0])
    for required_column in (
        "tenant_id",
        "shop_id",
        "platform_status",
        "creator_open_id",
        "creator_username",
    ):
        assert required_column in sql
    assert "lower(trim(sample_applications.creator_username))" in sql


@pytest.mark.asyncio
async def test_missing_identity_does_not_aggregate_other_applications() -> None:
    session = FakeSession()

    urls = await list_notification_product_image_urls(
        session,
        tenant_id=uuid4(),
        shop_id=uuid4(),
        application_id=uuid4(),
        platform_status="PENDING",
        creator_open_id="creator-1",
        creator_username=None,
        fallback_image_url="https://cdn.example/current.jpg",
    )

    assert urls == ("https://cdn.example/current.jpg",)
    assert session.statements == []


@pytest.mark.asyncio
async def test_grouped_application_uses_only_its_stored_product_images() -> None:
    session = FakeSession((("https://cdn.example/historical.jpg",),))

    urls = await list_notification_product_image_urls(
        session,
        tenant_id=uuid4(),
        shop_id=uuid4(),
        application_id=uuid4(),
        platform_status="PENDING",
        creator_open_id="creator-1",
        creator_username="creator_name",
        fallback_image_url=None,
        stored_image_urls=(
            "https://cdn.example/current-1.jpg",
            "https://cdn.example/current-2.jpg",
        ),
    )

    assert urls == (
        "https://cdn.example/current-1.jpg",
        "https://cdn.example/current-2.jpg",
    )
    assert session.statements == []
