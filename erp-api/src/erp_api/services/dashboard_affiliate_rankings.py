from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.dashboard_repository import DashboardFilters


def build_rankings(
    pages: list[tuple[str, list[dict[str, object]]]],
    shop_names: dict[str, str] | None = None,
) -> dict[str, object]:
    names = shop_names or {}
    videos: list[dict[str, object]] = []
    products: dict[tuple[str, str], dict[str, object]] = {}
    for shop_id, items in pages:
        for item in items:
            video_id = str(item.get("videoId") or item.get("id") or "").strip()
            if not video_id:
                continue
            videos.append(
                {
                    "id": f"{shop_id}:{video_id}",
                    "videoId": video_id,
                    "shopName": names.get(shop_id, shop_id),
                    "creatorUsername": item.get("creatorUsername"),
                    "title": item.get("title"),
                    "coverImageUrl": item.get("coverImageUrl"),
                    "videoPostTime": item.get("videoPostTime"),
                    "gmvMinor": max(0, int(item.get("gmvMinor") or 0)),
                    "views": item.get("views"),
                }
            )
            details = {
                str(product.get("productId") or product.get("id")): product
                for product in item.get("promotedProducts") or []
                if isinstance(product, dict)
                and (product.get("productId") or product.get("id"))
            }
            product_ids = set(details)
            product_ids.update(
                str(value) for value in item.get("promotedProductIds") or [] if value
            )
            for product_id in product_ids:
                key = (shop_id, product_id)
                product = products.setdefault(
                    key,
                    {
                        "id": f"{shop_id}:{product_id}",
                        "productId": product_id,
                        "shopName": names.get(shop_id, shop_id),
                        "title": None,
                        "coverImageUrl": None,
                        "videoCount": 0,
                        "singleProductVideoGmvMinor": None,
                        "singleProductVideoItemsSold": None,
                    },
                )
                detail = details.get(product_id) or {}
                product["title"] = product["title"] or detail.get("title")
                product["coverImageUrl"] = product["coverImageUrl"] or detail.get(
                    "coverImageUrl"
                )
                product["videoCount"] += 1
                if len(product_ids) == 1:
                    if item.get("gmvMinor") is not None:
                        product["singleProductVideoGmvMinor"] = (
                            product["singleProductVideoGmvMinor"] or 0
                        ) + max(0, int(item["gmvMinor"]))
                    if item.get("itemsSold") is not None:
                        product["singleProductVideoItemsSold"] = (
                            product["singleProductVideoItemsSold"] or 0
                        ) + max(0, int(item["itemsSold"]))

    videos.sort(key=lambda row: (-row["gmvMinor"], row["id"]))
    ordered_products = sorted(
        products.values(),
        key=lambda row: (
            -(row["singleProductVideoGmvMinor"] or 0),
            -row["videoCount"],
            row["id"],
        ),
    )
    return {"topVideos": videos, "topProducts": ordered_products}


class DashboardAffiliateRankingsRepository:
    def __init__(self, database: Database, affiliate: AffiliateCenterReadRepository):
        self._database = database
        self._affiliate = affiliate

    async def snapshot(
        self,
        tenant_id: UUID,
        filters: DashboardFilters,
        days: int,
        now: datetime,
    ) -> dict[str, object]:
        shops = await self._shops(tenant_id, filters)
        available: list[dict[str, object]] = []
        for shop in shops:
            timezone = shop["timezone"]
            if not timezone:
                continue
            end = now.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)
            query = self._query(shop, filters.currency, end, days)
            coverage = await self._affiliate.resolve_video_export_window(
                tenant_id, query
            )
            if coverage.window:
                available.append({**shop, "latestEnd": coverage.window[1]})
        if not available:
            return self._empty(days, len(shops))

        common_end = min(shop["latestEnd"] for shop in available)
        start = common_end - timedelta(days=days - 1)
        pages: list[tuple[str, list[dict[str, object]]]] = []
        complete_shops: list[dict[str, object]] = []
        for shop in available:
            query = self._query(shop, filters.currency, common_end, days)
            page = await self._affiliate.list_videos(
                tenant_id,
                query,
                page=1,
                page_size=50_000,
                sort="gmvMinor",
                order="desc",
                creator_open_id=None,
            )
            items = page.get("items") or []
            if page.get("run") is None or len(items) != page.get("total"):
                continue
            shop_key = str(shop["id"])
            pages.append((shop_key, items))
            complete_shops.append(shop)

        ranking = build_rankings(
            pages,
            {str(shop["id"]): shop["name"] for shop in complete_shops},
        )
        return {
            "period": {"start": start, "end": common_end},
            "days": days,
            "complete": len(complete_shops) == len(shops) and bool(shops),
            "shopCount": len(complete_shops),
            "expectedShopCount": len(shops),
            "totalVideos": len(ranking["topVideos"]),
            "totalProducts": len(ranking["topProducts"]),
            "topVideos": ranking["topVideos"][:100],
            "topProducts": ranking["topProducts"][:100],
            "productMetricScope": "single_product_videos_only",
        }

    async def _shops(self, tenant_id, filters):
        conditions = [
            Shop.tenant_id == tenant_id,
            Shop.status == "active",
            Shop.currency == filters.currency,
        ]
        if filters.platform:
            conditions.append(Shop.platform == filters.platform)
        if filters.site:
            conditions.append(Shop.region == filters.site)
        if filters.shop_id:
            conditions.append(Shop.id == filters.shop_id)
        async for session in self._database.session(tenant_id):
            rows = (
                await session.execute(
                    select(Shop.id, Shop.shop_name, Shop.timezone).where(*conditions)
                )
            ).all()
            return [
                {"id": row.id, "name": row.shop_name, "timezone": row.timezone}
                for row in rows
            ]
        return []

    @staticmethod
    def _query(shop, currency, end: date, days: int):
        return AffiliateCenterQuery(
            resource=AffiliateCenterResource.VIDEOS,
            shop_id=shop["id"],
            window_start=end - timedelta(days=days - 1),
            window_end=end,
            shop_timezone=shop["timezone"],
            currency=currency,
            filters={},
        )

    @staticmethod
    def _empty(days, expected):
        return {
            "period": None,
            "days": days,
            "complete": False,
            "shopCount": 0,
            "expectedShopCount": expected,
            "totalVideos": 0,
            "totalProducts": 0,
            "topVideos": [],
            "topProducts": [],
            "productMetricScope": "single_product_videos_only",
        }
