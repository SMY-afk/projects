from uuid import UUID

from sqlalchemy import func, select

from erp_api.models.analytics_snapshot import TikTokVideoContent
from erp_api.models.video_performance_snapshot import TikTokVideoPerformanceSnapshot
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_read_queries import (
    SortOrder,
    VideoSort,
    complete_video_run,
    video_sort_value,
)
from erp_api.services.affiliate_center_summary import (
    empty_video_summary,
    video_summary_from_row,
    video_summary_statement,
)
from erp_api.services.affiliate_video_media_enrichment import enrich_video_media
from erp_api.services.affiliate_video_window_coverage import (
    resolve_complete_video_chunks,
)
from erp_api.services.affiliate_video_window_read import aggregated_video_page


async def video_metric_page(
    session,
    tenant_id: UUID,
    query: AffiliateCenterQuery,
    *,
    page: int,
    page_size: int,
    sort: VideoSort,
    order: SortOrder,
    creator_open_id: str | None,
) -> dict[str, object]:
    chunks = await resolve_complete_video_chunks(session, tenant_id, query)
    if chunks is not None and len(chunks) > 1:
        result = await aggregated_video_page(
            session,
            tenant_id,
            query,
            chunks,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            creator_open_id=creator_open_id,
        )
        if result is not None:
            return result
        return _empty_video_page(query, page, page_size, sort, order)

    window_start, window_end = query.utc_window()
    run = await session.scalar(
        complete_video_run(tenant_id, query, window_start, window_end)
    )
    if run is None:
        return _empty_video_page(query, page, page_size, sort, order)

    snapshot = TikTokVideoPerformanceSnapshot
    content = TikTokVideoContent
    conditions = [
        snapshot.tenant_id == tenant_id,
        snapshot.shop_id == query.shop_id,
        snapshot.sync_run_id == run.id,
    ]
    if creator_open_id:
        conditions.append(content.fields["creatorOpenId"].astext == creator_open_id)
    joined = (
        select(snapshot, content)
        .join(
            content,
            (content.tenant_id == snapshot.tenant_id)
            & (content.shop_id == snapshot.shop_id)
            & (content.platform_video_id == snapshot.platform_video_id),
        )
        .where(*conditions)
    )
    total = await session.scalar(
        select(func.count()).select_from(joined.order_by(None).subquery())
    )
    summary_row = (
        await session.execute(
            video_summary_statement(tenant_id, query.shop_id, run.id, creator_open_id)
        )
    ).one()
    sort_value = video_sort_value(snapshot, content, sort)
    ordered = sort_value.asc() if order == "asc" else sort_value.desc()
    rows = await session.execute(
        joined.order_by(ordered.nullslast(), snapshot.platform_video_id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = await enrich_video_media(
        session,
        query.shop_id,
        [_video_dict(item, metadata) for item, metadata in rows],
    )
    return {
        "run": _run_dict(run),
        "query": query.canonical_dimensions(),
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": total or 0,
        "summary": video_summary_from_row(summary_row),
        "sort": sort,
        "order": order,
    }


def _empty_video_page(query, page, page_size, sort, order):
    return {
        "run": None,
        "query": query.canonical_dimensions(),
        "items": [],
        "page": page,
        "pageSize": page_size,
        "total": 0,
        "summary": empty_video_summary(),
        "sort": sort,
        "order": order,
    }


def _video_dict(snapshot, content) -> dict[str, object]:
    return {
        "id": snapshot.platform_video_id,
        "videoId": snapshot.platform_video_id,
        **content.fields,
        **snapshot.metrics,
        "sourceStatus": content.source_status,
        "status": content.status,
        "sourceUpdatedAt": snapshot.source_updated_at,
        "capturedAt": snapshot.captured_at,
    }


def _run_dict(run) -> dict[str, object]:
    return {
        "runId": run.id,
        "sourceKind": "official_api"
        if run.resource_type == "video"
        or str(run.job_id).startswith("official-affiliate")
        else "page_capture",
        "status": run.status,
        "fetchedCount": run.fetched_count,
        "persistedCount": run.persisted_count,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "freshAt": run.last_source_updated_at,
        "errorCategory": run.error_category,
        "errorSummary": run.error_summary,
    }
