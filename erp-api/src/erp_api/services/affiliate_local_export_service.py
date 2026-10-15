from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_live_account_range import resolve_live_range
from erp_api.services.affiliate_local_export_error import AffiliateLocalExportError
from erp_api.services.affiliate_local_export_pagination import (
    CENTER_PAGE_SIZE,
)
from erp_api.services.affiliate_local_export_pagination import (
    all_live_pages as _all_live_pages,
)
from erp_api.services.affiliate_local_export_pagination import (
    all_pages as _all_pages,
)
from erp_api.services.affiliate_local_export_rows import (
    creator_export_row,
    live_export_row,
    video_export_row,
)
from erp_api.services.affiliate_local_export_window import (
    AffiliateExportWindows,
    resolve_export_windows,
)


@dataclass(frozen=True)
class TargetShop:
    business_name: str
    product_line: str
    source_name: str


TARGET_SHOPS = (
    TargetShop("跨境3", "童车", "fanfu toy tool"),
    TargetShop("跨境7", "童车", "Akeleo-Drive"),
    TargetShop("跨境4", "遥控车", "Akeleo Fun Toys"),
    TargetShop("跨境12", "遥控车", "NEOPUP"),
    TargetShop("本土店", "遥控车", "Akeleo Toys"),
)


async def build_affiliate_local_export(
    tenant_id: UUID,
    window_start: date,
    window_end: date,
    *,
    now: datetime,
    shop_repository,
    center_repository,
    live_repository,
    targets: tuple[TargetShop, ...] = TARGET_SHOPS,
) -> dict[str, object]:
    source_shops = await shop_repository.list_shops(tenant_id)
    shops_by_name = {
        _normalized_name(item.get("shopName")): item for item in source_shops
    }
    missing = [
        target.source_name
        for target in targets
        if _normalized_name(target.source_name) not in shops_by_name
    ]
    if missing:
        raise AffiliateLocalExportError(
            "Required active ERP shops were not found: " + ", ".join(missing)
        )

    warnings: list[str] = []
    resolved_shops = []
    for target in targets:
        source = shops_by_name[_normalized_name(target.source_name)]
        shop_id = source.get("id")
        timezone = source.get("timezone")
        if (
            not isinstance(shop_id, UUID)
            or not isinstance(timezone, str)
            or not timezone
        ):
            raise AffiliateLocalExportError(
                f"{target.source_name} has an invalid id or timezone."
            )
        raw_currency = source.get("currency")
        currency = raw_currency if isinstance(raw_currency, str) else "USD"
        if not isinstance(raw_currency, str):
            warnings.append(
                f"{target.business_name} ({target.source_name}) has no currency; USD was used."
            )
        latest_dates = await center_repository.latest_available_dates(
            tenant_id,
            shop_id,
        )
        for resource in ("creators", "videos", "liveAccounts"):
            if latest_dates.get(resource) is None:
                raise AffiliateLocalExportError.incomplete_snapshot(
                    target.business_name,
                    resource,
                    (window_start, window_end),
                )
        resolved_shops.append((target, shop_id, timezone, currency, latest_dates))

    shops = []
    for target, shop_id, timezone, currency, latest_dates in resolved_shops:
        windows = resolve_export_windows(window_start, window_end, latest_dates)
        shops.append(
            await _export_shop(
                tenant_id,
                target,
                shop_id,
                timezone,
                currency,
                windows,
                now,
                center_repository,
                live_repository,
            )
        )
    return {
        "source": "local-erp-affiliate-center",
        "window": {"from": window_start.isoformat(), "to": window_end.isoformat()},
        "generatedAt": now,
        "shops": shops,
        "warnings": warnings,
    }


async def _export_shop(
    tenant_id,
    target,
    shop_id,
    timezone,
    currency,
    windows: AffiliateExportWindows,
    now,
    center_repository,
    live_repository,
):
    creator_window_start, creator_window_end = windows.creators
    video_window_start, video_window_end = windows.videos
    live_window_start, live_window_end = windows.live_accounts
    creator_query = AffiliateCenterQuery(
        AffiliateCenterResource.CREATORS,
        shop_id,
        creator_window_start,
        creator_window_end,
        timezone,
        currency,
        {},
    )
    video_query = AffiliateCenterQuery(
        AffiliateCenterResource.VIDEOS,
        shop_id,
        video_window_start,
        video_window_end,
        timezone,
        currency,
        {},
    )
    resolve_video_window = getattr(
        center_repository, "resolve_video_export_window", None
    )
    if resolve_video_window is not None:
        coverage = await resolve_video_window(tenant_id, video_query)
        if coverage.window is None:
            raise AffiliateLocalExportError.incomplete_snapshot(
                target.business_name,
                "videos",
                windows.videos,
                coverage.missing_dates,
            )
        if coverage.window != windows.videos:
            windows = replace(windows, videos=coverage.window)
            video_window_start, video_window_end = coverage.window
            video_query = replace(
                video_query,
                window_start=video_window_start,
                window_end=video_window_end,
            )
    creators, creator_total = await _all_pages(
        lambda page: center_repository.list_creators(
            tenant_id,
            creator_query,
            page=page,
            page_size=CENTER_PAGE_SIZE,
            sort="affiliateGmvMinor",
            order="desc",
        ),
        f"{target.business_name}.creators",
        snapshot_key="report",
        snapshot_error=AffiliateLocalExportError.incomplete_snapshot(
            target.business_name, "creators", windows.creators
        ),
    )
    videos, video_total = await _all_pages(
        lambda page: center_repository.list_videos(
            tenant_id,
            video_query,
            page=page,
            page_size=CENTER_PAGE_SIZE,
            sort="videoPostTime",
            order="desc",
            creator_open_id=None,
        ),
        f"{target.business_name}.videos",
        snapshot_key="run",
        snapshot_error=AffiliateLocalExportError.incomplete_snapshot(
            target.business_name, "videos", windows.videos
        ),
    )
    live_range = resolve_live_range(
        "custom",
        timezone,
        now,
        custom_from=live_window_start,
        custom_to=live_window_end,
    )
    lives, live_total = await _all_live_pages(
        tenant_id,
        shop_id,
        live_range.window_start,
        live_range.window_end,
        live_repository,
        f"{target.business_name}.liveAccounts",
    )
    return {
        "shopId": shop_id,
        "shopName": target.business_name,
        "sourceShopName": target.source_name,
        "sourceWindow": {
            "from": creator_window_start.isoformat(),
            "to": creator_window_end.isoformat(),
        },
        "sourceWindows": windows.as_dict(),
        "productLine": target.product_line,
        "currency": currency.upper(),
        "totals": {
            "creators": creator_total,
            "videos": video_total,
            "liveAccounts": live_total,
        },
        "creators": [creator_export_row(item) for item in creators],
        "videos": [video_export_row(item) for item in videos],
        "liveAccounts": [live_export_row(item) for item in lives],
    }


def _normalized_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
