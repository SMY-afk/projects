from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, desc, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import (
    AffiliateCreator,
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.models.shop import Shop
from erp_api.services.affiliate_creator_read_models import (
    creator_metric_dict,
    creator_report_dict,
)


class AffiliateCreatorRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_shops(self, tenant_id: UUID) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            rows = await session.execute(
                select(Shop.id, Shop.shop_name, Shop.timezone, Shop.currency)
                .where(Shop.tenant_id == tenant_id, Shop.status == "active")
                .order_by(Shop.shop_name)
            )
            return [
                {
                    "id": row.id,
                    "shopName": row.shop_name,
                    "timezone": row.timezone,
                    "currency": row.currency,
                }
                for row in rows
            ]
        return []

    async def list_reports(
        self, tenant_id: UUID, shop_id: UUID
    ) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            reports = list(
                await session.scalars(
                    select(AffiliateCreatorReport)
                    .where(
                        AffiliateCreatorReport.tenant_id == tenant_id,
                        AffiliateCreatorReport.shop_id == shop_id,
                    )
                    .order_by(
                        case((AffiliateCreatorReport.status == "complete", 0), else_=1),
                        desc(AffiliateCreatorReport.period_end),
                        desc(AffiliateCreatorReport.captured_at),
                    )
                )
            )
            if not reports:
                return []
            return [creator_report_dict(report) for report in reports]
        return []

    async def list_metrics(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        report_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            report = await session.scalar(
                select(AffiliateCreatorReport).where(
                    AffiliateCreatorReport.id == report_id,
                    AffiliateCreatorReport.tenant_id == tenant_id,
                    AffiliateCreatorReport.shop_id == shop_id,
                )
            )
            if report is None:
                return None
            total = await session.scalar(
                select(func.count())
                .select_from(AffiliateCreatorMetric)
                .where(AffiliateCreatorMetric.report_id == report_id)
                .where(
                    AffiliateCreatorMetric.tenant_id == tenant_id,
                    AffiliateCreatorMetric.shop_id == shop_id,
                )
            )
            result = await session.execute(
                select(AffiliateCreator, AffiliateCreatorMetric)
                .join(
                    AffiliateCreatorMetric,
                    (AffiliateCreatorMetric.creator_id == AffiliateCreator.id)
                    & (AffiliateCreatorMetric.tenant_id == AffiliateCreator.tenant_id)
                    & (AffiliateCreatorMetric.shop_id == AffiliateCreator.shop_id),
                )
                .where(
                    AffiliateCreatorMetric.report_id == report_id,
                    AffiliateCreatorMetric.tenant_id == tenant_id,
                    AffiliateCreatorMetric.shop_id == shop_id,
                    AffiliateCreator.tenant_id == tenant_id,
                    AffiliateCreator.shop_id == shop_id,
                )
                .order_by(
                    desc(AffiliateCreatorMetric.affiliate_gmv_minor),
                    AffiliateCreator.username,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return {
                "report": creator_report_dict(report),
                "items": [
                    creator_metric_dict(creator, metric) for creator, metric in result
                ],
                "page": page,
                "pageSize": page_size,
                "total": total or 0,
            }
        return None
