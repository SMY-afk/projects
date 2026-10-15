from uuid import uuid4

import pytest

from erp_api.services.affiliate_source_resolver import (
    AffiliateSourceResolver,
    is_official_affiliate_connection,
)


class FakeShopRepository:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []

    async def get_connection_status(self, tenant_id, shop_id):
        self.calls.append((tenant_id, shop_id))
        return self.connection


def _connection(*, profile="301", scopes=None, status="authorized"):
    return {
        "status": status,
        "appProfile": profile,
        "scopes": scopes
        or [
            "data.shop_analytics.public.read",
            "seller.creator_marketplace.read",
            "seller.affiliate_collaboration.read",
        ],
    }


def test_official_source_requires_the_dedicated_app_and_all_scopes() -> None:
    assert is_official_affiliate_connection(_connection()) is True
    assert is_official_affiliate_connection(_connection(profile="legacy")) is False
    assert (
        is_official_affiliate_connection(
            _connection(scopes=["data.shop_analytics.public.read"])
        )
        is False
    )
    assert is_official_affiliate_connection(_connection(status="disconnected")) is False


def test_ziniao_shop_keeps_browser_capture_even_with_official_scopes() -> None:
    assert (
        is_official_affiliate_connection(
            {**_connection(), "shopName": "Akeleo Toys"}
        )
        is False
    )


@pytest.mark.asyncio
async def test_source_resolution_is_scoped_to_the_requested_shop() -> None:
    repository = FakeShopRepository(_connection())
    resolver = AffiliateSourceResolver(repository)
    tenant_id, shop_id = uuid4(), uuid4()

    assert await resolver.source_kind(tenant_id, shop_id) == "official_api"
    assert await resolver.capture_mode(tenant_id, shop_id) == "official_api_owned"
    assert repository.calls == [(tenant_id, shop_id), (tenant_id, shop_id)]


@pytest.mark.asyncio
async def test_source_resolution_routes_akeleo_toys_to_ziniao_capture() -> None:
    repository = FakeShopRepository({**_connection(), "shopName": "Akeleo Toys"})
    resolver = AffiliateSourceResolver(repository)

    assert await resolver.source_kind(uuid4(), uuid4()) == "page_capture"
