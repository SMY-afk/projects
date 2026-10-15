from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select

from erp_api.models.analytics_snapshot import TikTokVideoContent
from erp_api.models.video_performance_snapshot import TikTokVideoPerformanceSnapshot
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_read_queries import (
    SortOrder,
    VideoSort,
    complete_video_run,
)
from erp_api.services.affiliate_center_summary import video_summary_from_rows
from erp_api.services.affiliate_video_media_enrichment import enrich_video_media
from erp_api.services.affiliate_video_window_aggregation import aggregate_video_rows


async def aggregated_video_page(
    session,
    tenant_id: UUID,
    query: AffiliateCenterQuery,
    chunks: list[AffiliateCenterQuery],
    *,
    page: int,
    page_size: int,
    sort: VideoSort,
    order: SortOrder,
    creator_open_id: str | None,
) -> dict[str, object] | None:
    runs = []
    for chunk in chunks:
        window_start, window_end = chunk.utc_window()
        run = await session.scalar(
            complete_video_run(tenant_id, chunk, window_start, window_end)
        )
        if run is None:
            return None
        runs.append(run)

    snapshot = TikTokVideoPerformanceSnapshot
    content = TikTokVideoContent
    rows = (
        await session.execute(
            select(snapshot, content)
            .join(
                content,
                (content.tenant_id == snapshot.tenant_id)
                & (content.shop_id == snapshot.shop_id)
                & (content.platform_video_id == snapshot.platform_video_id),
            )
            .where(
                snapshot.tenant_id == tenant_id,
                snapshot.shop_id == query.shop_id,
                snapshot.sync_run_id.in_([run.id for run in runs]),
            )
        )
    ).all()
    aggregated = aggregate_video_rows(list(rows))
    if creator_open_id:
        aggregated = [
            row
            for row in aggregated
            if row[1].fields.get("creatorOpenId") == creator_open_id
        ]
    ordered = _sort_rows(aggregated, sort, order)
    offset = (page - 1) * page_size
    items = await enrich_video_media(
        session,
        query.shop_id,
        [
            _video_dict(item, metadata)
            for item, metadata in ordered[offset : offset + page_size]
        ],
    )
    return {
        "run": _combined_run(runs),
        "query": query.canonical_dimensions(),
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": len(ordered),
        "summary": video_summary_from_rows(aggregated),
        "sort": sort,
        "order": order,
    }


def _sort_rows(rows, sort: VideoSort, order: SortOrder):
    def value(row):
        snapshot, content = row
        raw = (
            content.fields.get("videoPostTime")
            if sort == "videoPostTime"
            else snapshot.metrics.get(sort)
        )
        return (
            str(raw) if sort == "videoPostTime" and raw is not None else _decimal(raw)
        )

    present = [row for row in rows if value(row) is not None]
    missing = [row for row in rows if value(row) is None]
    present.sort(key=lambda row: row[0].platform_video_id)
    present.sort(key=value, reverse=order == "desc")
    missing.sort(key=lambda row: row[0].platform_video_id)
    return present + missing


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


def _combined_run(runs) -> dict[str, object]:
    latest = max(runs, key=lambda run: run.finished_at or run.started_at)
    fresh_values = [
        run.last_source_updated_at for run in runs if run.last_source_updated_at
    ]
    return {
        "runId": latest.id,
        "status": "succeeded",
        "fetchedCount": sum(run.fetched_count for run in runs),
        "persistedCount": sum(run.persisted_count for run in runs),
        "startedAt": min(run.started_at for run in runs),
        "finishedAt": max(run.finished_at for run in runs if run.finished_at),
        "freshAt": max(fresh_values, default=None),
        "errorCategory": None,
        "errorSummary": None,
    }


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
