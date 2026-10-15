from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from erp_api.services.affiliate_center_source import AffiliateSourceKind

AffiliateCaptureMode = Literal["browser_daemon_owned", "official_api_owned"]

OFFICIAL_AFFILIATE_APP_PROFILE = "301"
OFFICIAL_AFFILIATE_SCOPES = frozenset(
    {
        "data.shop_analytics.public.read",
        "seller.creator_marketplace.read",
        "seller.affiliate_collaboration.read",
    }
)
BROWSER_CAPTURE_SHOP_NAMES = frozenset({"Akeleo Toys"})


def is_official_affiliate_connection(connection: Mapping[str, object] | None) -> bool:
    if not connection or connection.get("status") != "authorized":
        return False
    if connection.get("shopName") in BROWSER_CAPTURE_SHOP_NAMES:
        return False
    scopes = {
        str(scope).strip()
        for scope in connection.get("scopes", [])
        if str(scope).strip()
    }
    return (
        connection.get("appProfile") == OFFICIAL_AFFILIATE_APP_PROFILE
        and OFFICIAL_AFFILIATE_SCOPES.issubset(scopes)
    )


class AffiliateSourceResolver:
    """Select the source per tenant/shop without sharing capture state."""

    def __init__(self, shop_repository) -> None:
        self._shop_repository = shop_repository

    async def source_kind(self, tenant_id: UUID, shop_id: UUID) -> AffiliateSourceKind:
        connection = await self._shop_repository.get_connection_status(
            tenant_id, shop_id
        )
        return (
            "official_api"
            if is_official_affiliate_connection(connection)
            else "page_capture"
        )

    async def capture_mode(
        self, tenant_id: UUID, shop_id: UUID
    ) -> AffiliateCaptureMode:
        source = await self.source_kind(tenant_id, shop_id)
        return (
            "official_api_owned"
            if source == "official_api"
            else "browser_daemon_owned"
        )
