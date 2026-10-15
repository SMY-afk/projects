from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select

from erp_api.models.affiliate_creator import AffiliateCreator, AffiliateCreatorMetric
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_read_queries import (
    CREATOR_SORTS,
    CreatorSort,
    SortOrder,
)
from erp_api.services.affiliate_center_summary import (
    creator_summary_from_row,
    creator_summary_statement,
)
from erp_api.services.affiliate_creator_avatar_query import (
    video_avatars_for_usernames,
)
from erp_api.services.affiliate_creator_read_models import (
    creator_metric_dict,
    creator_report_dict,
)


async def creator_metric_page(
    session,
    tenant_id: UUID,
    query: AffiliateCenterQuery,
    report,
    *,
    page: int,
    page_size: int,
    sort: CreatorSort,
    order: SortOrder,
) -> dict[str, object]:
    conditions = (
        AffiliateCreatorMetric.tenant_id == tenant_id,
        AffiliateCreatorMetric.shop_id == query.shop_id,
        AffiliateCreatorMetric.report_id == report.id,
    )
    total = await session.scalar(
        select(func.count()).select_from(AffiliateCreatorMetric).where(*conditions)
    )
    summary_row = (
        await session.execute(
            creator_summary_statement(tenant_id, query.shop_id, report.id)
        )
    ).one()
    sort_column = CREATOR_SORTS[sort]
    ordered = sort_column.asc() if order == "asc" else sort_column.desc()
    rows = (
        await session.execute(
            select(AffiliateCreator, AffiliateCreatorMetric)
            .join(
                AffiliateCreatorMetric,
                (AffiliateCreatorMetric.creator_id == AffiliateCreator.id)
                & (AffiliateCreatorMetric.tenant_id == AffiliateCreator.tenant_id)
                & (AffiliateCreatorMetric.shop_id == AffiliateCreator.shop_id),
            )
            .where(*conditions)
            .order_by(ordered.nullslast(), AffiliateCreator.username.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    missing_avatar_usernames = {
        creator.username_normalized
        for creator, _metric in rows
        if not creator.avatar_url and creator.username_normalized
    }
    video_avatars = {}
    if missing_avatar_usernames:
        avatar_rows = await session.execute(
            video_avatars_for_usernames(
                tenant_id,
                query.shop_id,
                missing_avatar_usernames,
            )
        )
        video_avatars = {
            username: avatar_url for username, avatar_url in avatar_rows.all()
        }
    return {
        "report": creator_report_dict(report),
        "items": [
            creator_metric_dict(
                creator,
                metric,
                fallback_avatar_url=video_avatars.get(creator.username_normalized),
            )
            for creator, metric in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total or 0,
        "summary": creator_summary_for_report(summary_row, report),
        "sort": sort,
        "order": order,
    }


def creator_summary_for_report(row, report) -> dict[str, int]:
    summary = creator_summary_from_row(row)
    metadata = report.source_metadata
    if not isinstance(metadata, Mapping):
        return summary
    if metadata.get("provider") != "tiktok_compass_creator_xlsx_seller_center":
        return summary
    try:
        source_total = int(metadata["sourceRowCount"])
        unidentified = int(metadata["unidentifiedRowCount"])
    except (KeyError, TypeError, ValueError):
        return summary
    if unidentified >= 0 and source_total == summary["creatorCount"] + unidentified:
        summary["creatorCount"] = source_total
    return summary
