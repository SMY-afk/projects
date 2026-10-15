from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.affiliate_creator_detail import (
    AffiliateCreatorDetailItem,
    AffiliateCreatorDetailReport,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_metric_parse_support import creator_username_aliases


class AffiliateCreatorDetailReadRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def creator(
        self, tenant_id: UUID, shop_id: UUID, creator_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            creator = await session.scalar(
                select(AffiliateCreator).where(
                    AffiliateCreator.tenant_id == tenant_id,
                    AffiliateCreator.shop_id == shop_id,
                    AffiliateCreator.id == creator_id,
                )
            )
            if creator is None:
                return None
            return {
                "id": creator.id,
                "username": creator.username,
                "creatorOpenId": creator.creator_open_id,
                "avatarUrl": creator.avatar_url,
                "firstSeenAt": creator.first_seen_at,
                "lastSeenAt": creator.last_seen_at,
            }
        raise RuntimeError("Tenant database session was not created.")

    async def list_items(
        self,
        tenant_id: UUID,
        creator_id: UUID,
        query: AffiliateCenterQuery,
        resource_kind: str,
        *,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        window_start, window_end = query.utc_window()
        async for session in self._database.session(tenant_id):
            creator_ids = await _creator_alias_ids(
                session, tenant_id, query.shop_id, creator_id
            )
            if not creator_ids:
                return _empty(page, page_size, None)
            report = await session.scalar(
                select(AffiliateCreatorDetailReport)
                .where(
                    AffiliateCreatorDetailReport.tenant_id == tenant_id,
                    AffiliateCreatorDetailReport.shop_id == query.shop_id,
                    AffiliateCreatorDetailReport.creator_id.in_(creator_ids),
                    AffiliateCreatorDetailReport.resource_kind == resource_kind,
                    AffiliateCreatorDetailReport.window_start_utc == window_start,
                    AffiliateCreatorDetailReport.window_end_utc == window_end,
                    AffiliateCreatorDetailReport.shop_timezone == query.shop_timezone,
                    AffiliateCreatorDetailReport.currency == query.currency,
                    AffiliateCreatorDetailReport.status == "complete",
                )
                .order_by(
                    desc(AffiliateCreatorDetailReport.finished_at),
                    desc(AffiliateCreatorDetailReport.revision_no),
                )
                .limit(1)
            )
            latest = await session.scalar(
                select(AffiliateCreatorDetailReport)
                .where(
                    AffiliateCreatorDetailReport.tenant_id == tenant_id,
                    AffiliateCreatorDetailReport.shop_id == query.shop_id,
                    AffiliateCreatorDetailReport.creator_id.in_(creator_ids),
                    AffiliateCreatorDetailReport.resource_kind == resource_kind,
                    AffiliateCreatorDetailReport.window_start_utc == window_start,
                    AffiliateCreatorDetailReport.window_end_utc == window_end,
                )
                .order_by(desc(AffiliateCreatorDetailReport.captured_at))
                .limit(1)
            )
            if report is None:
                return _empty(page, page_size, latest)
            conditions = (
                AffiliateCreatorDetailItem.tenant_id == tenant_id,
                AffiliateCreatorDetailItem.shop_id == query.shop_id,
                AffiliateCreatorDetailItem.report_id == report.id,
            )
            total = await session.scalar(
                select(func.count())
                .select_from(AffiliateCreatorDetailItem)
                .where(*conditions)
            )
            items = await session.scalars(
                select(AffiliateCreatorDetailItem)
                .where(*conditions)
                .order_by(AffiliateCreatorDetailItem.captured_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return {
                "report": _report(report),
                "items": [
                    {
                        "id": item.platform_content_id,
                        **item.identity,
                        **item.metrics,
                        "extensions": item.extensions,
                        "capturedAt": item.captured_at,
                    }
                    for item in items
                ],
                "page": page,
                "pageSize": page_size,
                "total": total or 0,
            }
        raise RuntimeError("Tenant database session was not created.")

    async def statuses(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        creator_id: UUID,
    ) -> list[dict[str, object]]:
        result = []
        async for session in self._database.session(tenant_id):
            creator_ids = await _creator_alias_ids(
                session, tenant_id, shop_id, creator_id
            )
            for kind in ("video", "live", "product", "product_card"):
                latest = await session.scalar(
                    select(AffiliateCreatorDetailReport)
                    .where(
                        AffiliateCreatorDetailReport.tenant_id == tenant_id,
                        AffiliateCreatorDetailReport.shop_id == shop_id,
                        AffiliateCreatorDetailReport.creator_id.in_(creator_ids),
                        AffiliateCreatorDetailReport.resource_kind == kind,
                    )
                    .order_by(desc(AffiliateCreatorDetailReport.captured_at))
                    .limit(1)
                )
                result.append(
                    {
                        "resource": kind,
                        "status": latest.status if latest else "never_synced",
                        "report": _report(latest) if latest else None,
                    }
                )
            return result
        raise RuntimeError("Tenant database session was not created.")


def _report(report) -> dict[str, object]:
    return {
        "id": report.id,
        "resource": report.resource_kind,
        "status": report.status,
        "revisionNo": report.revision_no,
        "expectedTotal": report.expected_total,
        "recordsUnique": report.records_unique,
        "capturedAt": report.captured_at,
        "finishedAt": report.finished_at,
        "completenessReason": report.completeness_reason,
        "currency": report.currency,
        "shopTimezone": report.shop_timezone,
    }


def _empty(page: int, page_size: int, latest) -> dict[str, object]:
    return {
        "report": _report(latest) if latest else None,
        "items": [],
        "page": page,
        "pageSize": page_size,
        "total": 0,
    }


async def _creator_alias_ids(
    session, tenant_id: UUID, shop_id: UUID, creator_id: UUID
) -> tuple[UUID, ...]:
    creator = await session.scalar(
        select(AffiliateCreator).where(
            AffiliateCreator.tenant_id == tenant_id,
            AffiliateCreator.shop_id == shop_id,
            AffiliateCreator.id == creator_id,
        )
    )
    if creator is None:
        return ()
    aliases = creator_username_aliases(creator.username_normalized)
    ids = await session.scalars(
        select(AffiliateCreator.id).where(
            AffiliateCreator.tenant_id == tenant_id,
            AffiliateCreator.shop_id == shop_id,
            AffiliateCreator.username_normalized.in_(aliases),
        )
    )
    return tuple(ids)
