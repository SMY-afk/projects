from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from erp_api.services.affiliate_center_contract import AffiliateCenterResource
from erp_api.services.affiliate_schedule_queries import ScheduledShop

TARGET_AFFILIATE_SHOP_NAMES = frozenset(
    {
        "fanfu toy tool",
        "Akeleo-Drive",
        "Akeleo Fun Toys",
        "NEOPUP",
        "Akeleo Toys",
    }
)
AvailabilityProvider = Callable[
    [UUID, UUID, AffiliateCenterResource], Awaitable[date | None]
]


async def resolve_shop_cutoffs(
    shops: list[ScheduledShop],
    resource: AffiliateCenterResource,
    now: datetime,
    availability_provider: AvailabilityProvider | None,
) -> dict[UUID, date]:
    if availability_provider is None:
        return {}
    cutoffs: dict[UUID, date] = {}
    for shop in shops:
        if shop.source_name not in TARGET_AFFILIATE_SHOP_NAMES:
            continue
        observed = await availability_provider(shop.tenant_id, shop.shop_id, resource)
        if observed is None:
            continue
        local_today = now.astimezone(ZoneInfo(shop.timezone)).date()
        if observed > local_today:
            continue
        cutoffs[shop.shop_id] = observed
    return cutoffs
