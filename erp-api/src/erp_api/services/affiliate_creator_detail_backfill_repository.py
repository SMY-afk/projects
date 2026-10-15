from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import desc, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator, AffiliateCreatorReport
from erp_api.models.affiliate_creator_detail import AffiliateCreatorDetailReport
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_metric_parse_support import creator_username_aliases


@dataclass(frozen=True)
class CreatorDetailBackfillTarget:
    query: AffiliateCenterQuery
    platform_shop_id: str


class AffiliateCreatorDetailBackfillRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def target_for_window(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        platform_shop_id: str,
        window_start: date,
        window_end: date,
    ) -> CreatorDetailBackfillTarget | None:
        async for session in self._database.session(tenant_id):
            report = await session.scalar(
                select(AffiliateCreatorReport)
                .where(
                    AffiliateCreatorReport.tenant_id == tenant_id,
                    AffiliateCreatorReport.shop_id == shop_id,
                    AffiliateCreatorReport.status == "complete",
                    AffiliateCreatorReport.period_start == window_start,
                    AffiliateCreatorReport.period_end == window_end,
                )
                .order_by(desc(AffiliateCreatorReport.captured_at))
                .limit(1)
            )
            if report is None:
                return None
            return CreatorDetailBackfillTarget(
                query=AffiliateCenterQuery(
                    resource=AffiliateCenterResource.CREATORS,
                    shop_id=shop_id,
                    window_start=report.period_start,
                    window_end=report.period_end,
                    shop_timezone=report.shop_timezone,
                    currency=report.currency,
                    filters={},
                ),
                platform_shop_id=platform_shop_id,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def link_identity(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        username_normalized: str,
        platform_creator_id: str,
        avatar_url: str | None,
    ) -> tuple[UUID, ...]:
        aliases = creator_username_aliases(username_normalized)
        async for session in self._database.session(tenant_id):
            creators = list(
                await session.scalars(
                    select(AffiliateCreator).where(
                        AffiliateCreator.tenant_id == tenant_id,
                        AffiliateCreator.shop_id == shop_id,
                        AffiliateCreator.username_normalized.in_(aliases),
                    )
                )
            )
            linked: list[UUID] = []
            for creator in creators:
                identifiers = dict(creator.source_identifiers or {})
                existing = identifiers.get("tiktok_page_creator_id")
                if existing not in {None, platform_creator_id}:
                    continue
                identifiers["tiktok_page_creator_id"] = platform_creator_id
                creator.source_identifiers = identifiers
                if avatar_url and not creator.avatar_url:
                    creator.avatar_url = avatar_url
                linked.append(creator.id)
            await session.commit()
            return tuple(linked)
        raise RuntimeError("Tenant database session was not created.")

    async def is_complete(
        self,
        tenant_id: UUID,
        target: CreatorDetailBackfillTarget,
        creator_ids: tuple[UUID, ...],
    ) -> bool:
        if not creator_ids:
            return True
        window_start, window_end = target.query.utc_window()
        async for session in self._database.session(tenant_id):
            count = await session.scalar(
                select(
                    func.count(
                        func.distinct(AffiliateCreatorDetailReport.resource_kind)
                    )
                ).where(
                    AffiliateCreatorDetailReport.tenant_id == tenant_id,
                    AffiliateCreatorDetailReport.shop_id == target.query.shop_id,
                    AffiliateCreatorDetailReport.creator_id.in_(creator_ids),
                    AffiliateCreatorDetailReport.status == "complete",
                    AffiliateCreatorDetailReport.window_start_utc == window_start,
                    AffiliateCreatorDetailReport.window_end_utc == window_end,
                    AffiliateCreatorDetailReport.shop_timezone
                    == target.query.shop_timezone,
                    AffiliateCreatorDetailReport.currency == target.query.currency,
                )
            )
            return (count or 0) == 4
        raise RuntimeError("Tenant database session was not created.")
