from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.sample_application import SampleApplication
from erp_api.models.shop import Shop
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.dashboard_affiliate_metrics import (
    efficiency_payload,
    empty_efficiency,
    identity_keys,
    level_items,
)
from erp_api.services.dashboard_ranges import TimeWindow
from erp_api.services.dashboard_repository import DashboardFilters

APPROVED_STATUSES = (
    "AWAITING_SHIPMENT",
    "SHIPPED",
    "CONTENT_PENDING",
    "COMPLETED",
    "OPS_COMPLETED",
)
SHIPPED_STATUSES = ("SHIPPED", "CONTENT_PENDING", "COMPLETED", "OPS_COMPLETED")
COMPLETED_STATUSES = ("COMPLETED", "OPS_COMPLETED")


class DashboardAffiliateRepository:
    def __init__(
        self,
        database: Database,
        affiliate_repository: AffiliateCenterReadRepository,
    ) -> None:
        self._database = database
        self._affiliate_repository = affiliate_repository

    async def snapshot(
        self,
        tenant_id: UUID,
        filters: DashboardFilters,
        window: TimeWindow,
    ) -> dict[str, object]:
        shops = await self._shops(tenant_id, filters)
        shop_ids = [shop["id"] for shop in shops]
        sample_funnel, levels, sample_statuses = await self._sample_data(
            tenant_id, shop_ids
        )
        efficiency = await self._creator_efficiency(
            tenant_id,
            shops,
            filters.currency,
            window,
            sample_statuses,
        )
        return {
            "sampleFunnel": sample_funnel,
            "creatorLevels": levels,
            "creatorEfficiency": efficiency,
        }

    async def _shops(
        self, tenant_id: UUID, filters: DashboardFilters
    ) -> list[dict[str, object]]:
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

    async def _sample_data(self, tenant_id: UUID, shop_ids: list[UUID]):
        empty_funnel = {
            "scope": "current_projection_all_time",
            "applicationCount": 0,
            "approvedCount": 0,
            "shippedCount": 0,
            "completedCount": 0,
            "cancelledCount": 0,
            "sourceObservedAt": None,
        }
        if not shop_ids:
            return empty_funnel, level_items({}), {}
        conditions = (
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id.in_(shop_ids),
            SampleApplication.is_current_projection.is_(True),
        )
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(
                        func.count(SampleApplication.id),
                        func.count(SampleApplication.id).filter(
                            SampleApplication.platform_status.in_(APPROVED_STATUSES)
                        ),
                        func.count(SampleApplication.id).filter(
                            SampleApplication.platform_status.in_(SHIPPED_STATUSES)
                        ),
                        func.count(SampleApplication.id).filter(
                            SampleApplication.platform_status.in_(COMPLETED_STATUSES)
                        ),
                        func.count(SampleApplication.id).filter(
                            SampleApplication.platform_status.contains("CANCELLED")
                        ),
                        func.max(SampleApplication.source_observed_at),
                    ).where(*conditions)
                )
            ).one()
            level_rows = (
                await session.execute(
                    select(SampleApplication.creator_level, func.count())
                    .where(*conditions)
                    .group_by(SampleApplication.creator_level)
                )
            ).all()
            status_rows = (
                await session.execute(
                    select(
                        SampleApplication.shop_id,
                        SampleApplication.creator_open_id,
                        SampleApplication.creator_username,
                        SampleApplication.platform_status,
                    )
                    .where(*conditions)
                    .order_by(SampleApplication.updated_at.desc())
                )
            ).all()
            statuses: dict[tuple[UUID, str], str] = {}
            for item in status_rows:
                for key in identity_keys(item.creator_open_id, item.creator_username):
                    statuses.setdefault((item.shop_id, key), item.platform_status)
            counts = {level: int(count) for level, count in level_rows if level}
            funnel = {
                "scope": "current_projection_all_time",
                "applicationCount": int(row[0] or 0),
                "approvedCount": int(row[1] or 0),
                "shippedCount": int(row[2] or 0),
                "completedCount": int(row[3] or 0),
                "cancelledCount": int(row[4] or 0),
                "sourceObservedAt": row[5],
            }
            return funnel, level_items(counts), statuses
        return empty_funnel, level_items({}), {}

    async def _creator_efficiency(
        self,
        tenant_id: UUID,
        shops: list[dict[str, object]],
        currency: str,
        window: TimeWindow,
        sample_statuses: dict[tuple[UUID, str], str],
    ) -> dict[str, object]:
        period = await self._common_period(tenant_id, shops, currency, window)
        if period is None:
            return empty_efficiency()
        pages = await self._creator_pages(tenant_id, shops, currency, period)
        start, end = period
        if len(pages) < len(shops) and (end - start).days >= 7:
            fallback_period = (end - timedelta(days=6), end)
            fallback_pages = await self._creator_pages(
                tenant_id, shops, currency, fallback_period
            )
            if len(fallback_pages) > len(pages):
                period = fallback_period
                pages = fallback_pages
        return efficiency_payload(
            pages,
            sample_statuses,
            period,
            expected_shop_count=len(shops),
        )

    async def _creator_pages(
        self,
        tenant_id: UUID,
        shops: list[dict[str, object]],
        currency: str,
        period: tuple[date, date],
    ) -> list[tuple[dict[str, object], dict[str, object]]]:
        start, end = period
        pages: list[tuple[dict[str, object], dict[str, object]]] = []
        for shop in shops:
            timezone = shop["timezone"]
            if not isinstance(timezone, str) or not timezone:
                continue
            query = AffiliateCenterQuery(
                resource=AffiliateCenterResource.CREATORS,
                shop_id=shop["id"],
                window_start=start,
                window_end=end,
                shop_timezone=timezone,
                currency=currency,
                filters={},
            )
            page = await self._affiliate_repository.list_creators(
                tenant_id,
                query,
                page=1,
                page_size=50_000,
                sort="affiliateGmvMinor",
                order="desc",
            )
            if page.get("report") is not None:
                pages.append((shop, page))
        return pages

    async def _common_period(
        self,
        tenant_id: UUID,
        shops: list[dict[str, object]],
        currency: str,
        window: TimeWindow,
    ) -> tuple[date, date] | None:
        if not shops:
            return None
        shop_ids = [shop["id"] for shop in shops]
        async for session in self._database.session(tenant_id):
            rows = (
                await session.execute(
                    select(
                        AffiliateCreatorReport.shop_id,
                        func.max(AffiliateCreatorReport.period_end),
                    )
                    .where(
                        AffiliateCreatorReport.tenant_id == tenant_id,
                        AffiliateCreatorReport.shop_id.in_(shop_ids),
                        AffiliateCreatorReport.currency == currency,
                        AffiliateCreatorReport.status == "complete",
                    )
                    .group_by(AffiliateCreatorReport.shop_id)
                )
            ).all()
            latest = {row[0]: row[1] for row in rows if row[1] is not None}
            if len(latest) != len(shop_ids):
                return None
            requested_end = (window.end - timedelta(microseconds=1)).date()
            days = max(1, (requested_end - window.start.date()).days + 1)
            common_end = min(requested_end, *latest.values())
            return common_end - timedelta(days=days - 1), common_end
        return None
