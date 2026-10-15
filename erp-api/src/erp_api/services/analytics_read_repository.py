from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Numeric, case, cast, literal, select

from erp_api.infrastructure.database import Database
from erp_api.models.analytics_snapshot import TikTokLiveSession, TikTokVideoContent
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.scraped_data import ScrapedData
from erp_api.models.shop import Shop
from erp_api.services.media_image_repository import (
    resolve_product_images,
    resolve_video_covers,
)
from erp_api.services.video_performance_fields import merge_windowed_fields
from erp_api.services.video_performance_query import video_performance_statement


@dataclass(frozen=True)
class StoredAnalyticsContent:
    platform_external_id: str
    fields: dict[str, object]
    source_status: str | None
    status: str | None
    source_updated_at: datetime | None
    observed_at: datetime


@dataclass(frozen=True)
class StoredAnalyticsSyncRun:
    id: UUID
    resource_type: str
    status: str
    attempt_count: int
    fetched_count: int
    persisted_count: int
    error_category: str | None
    error_summary: str | None
    fresh_at: datetime | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class StoredVideoWindowState:
    finished_at: datetime
    latest_available_date: date | None


class AnalyticsReadRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def shop_exists(self, tenant_id: UUID, shop_id: UUID) -> bool:
        async for session in self._database.session(tenant_id):
            return (
                await session.scalar(select(Shop.id).where(Shop.id == shop_id))
                is not None
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_shop_timezone(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        async for session in self._database.session(tenant_id):
            return await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
        raise RuntimeError("Tenant database session was not created.")

    async def list_content(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        resource_type: Literal["video", "live"],
        limit: int,
        sort_by: Literal["gmv", "gpm", "publishedAt", "startedAt"],
        sort_order: Literal["asc", "desc"],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        currency: str | None = None,
        account_type: str | None = None,
    ) -> list[StoredAnalyticsContent]:
        if (window_start is None) != (window_end is None):
            raise ValueError("Both window_start and window_end are required.")
        allowed_sorts = {
            "video": {"gmv", "gpm", "publishedAt"},
            "live": {"gmv", "startedAt"},
        }
        if sort_by not in allowed_sorts[resource_type]:
            raise ValueError(
                f"Unsupported {resource_type} analytics sort field: {sort_by}."
            )
        if resource_type == "video" and window_start is not None:
            if not currency or not account_type:
                raise ValueError(
                    "Windowed video rankings require currency and account_type."
                )
            async for session in self._database.session(tenant_id):
                rows = (
                    await session.execute(
                        video_performance_statement(
                            tenant_id,
                            shop_id,
                            window_start=window_start,
                            window_end=window_end,
                            currency=currency,
                            account_type=account_type,
                            limit=limit,
                            sort_by=sort_by,
                            sort_order=sort_order,
                        )
                    )
                ).all()
                return await _stored_windowed_video_rows(session, shop_id, rows)
            raise RuntimeError("Tenant database session was not created.")
        model, external_id = (
            (TikTokVideoContent, TikTokVideoContent.platform_video_id)
            if resource_type == "video"
            else (TikTokLiveSession, TikTokLiveSession.platform_live_id)
        )
        async for session in self._database.session(tenant_id):
            order_by = [
                model.source_updated_at.desc().nullslast(),
                model.observed_at.desc(),
            ]
            json_key = {
                "gmv": "gmvAmount",
                "gpm": "gpmAmount",
                "publishedAt": "videoPostTime",
                "startedAt": "startTime",
            }[sort_by]
            field_text = model.fields[json_key].astext
            if sort_by in {"gmv", "gpm", "startedAt"}:
                sort_value = case(
                    (
                        field_text.op("~")(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$"),
                        cast(field_text, Numeric(20, 4)),
                    ),
                    else_=None,
                )
            else:
                sort_value = field_text
            ordered_value = (
                sort_value.asc() if sort_order == "asc" else sort_value.desc()
            )
            order_by.insert(0, ordered_value.nullslast())
            selected = select(
                external_id,
                model.fields,
                model.source_status,
                model.status,
                model.source_updated_at,
                model.observed_at,
            )
            if resource_type == "video":
                selected = selected.add_columns(ScrapedData.raw_data).outerjoin(
                    ScrapedData,
                    (ScrapedData.tenant_id == tenant_id)
                    & (ScrapedData.data_type == "seller_video_completion")
                    & (
                        ScrapedData.platform_id
                        == literal("seller_video_completion:") + external_id
                    ),
                )
            elif account_type:
                selected = selected.where(
                    model.fields["accountType"].astext == account_type
                )
            if resource_type == "live" and window_start is not None:
                live_start_text = model.fields["startTime"].astext
                live_start = cast(live_start_text, Numeric(20, 4))
                selected = selected.where(
                    live_start_text.op("~")(r"^\d+(?:\.\d+)?$"),
                    live_start >= window_start.timestamp(),
                    live_start < window_end.timestamp(),
                )
            rows = (
                await session.execute(
                    selected.where(model.shop_id == shop_id)
                    .order_by(*order_by)
                    .limit(limit)
                )
            ).all()
            if resource_type == "live":
                return [StoredAnalyticsContent(*row) for row in rows]
            return await _stored_video_rows(session, shop_id, rows)
        raise RuntimeError("Tenant database session was not created.")

    async def get_video_window_state(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        window_start: datetime,
        window_end: datetime,
        currency: str,
        account_type: str,
    ) -> StoredVideoWindowState | None:
        async for session in self._database.session(tenant_id):
            run = await session.scalar(
                select(AnalyticsSyncRun)
                .where(
                    AnalyticsSyncRun.tenant_id == tenant_id,
                    AnalyticsSyncRun.shop_id == shop_id,
                    AnalyticsSyncRun.resource_type == "video",
                    AnalyticsSyncRun.window_start == window_start,
                    AnalyticsSyncRun.window_end == window_end,
                    AnalyticsSyncRun.currency == currency,
                    AnalyticsSyncRun.account_type == account_type,
                    AnalyticsSyncRun.status == "succeeded",
                    AnalyticsSyncRun.finished_at.is_not(None),
                )
                .order_by(AnalyticsSyncRun.finished_at.desc())
                .limit(1)
            )
            if run is None or run.finished_at is None:
                return None
            return StoredVideoWindowState(
                finished_at=run.finished_at,
                latest_available_date=run.latest_available_date,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def list_sync_runs(
        self, tenant_id: UUID, shop_id: UUID, *, limit: int
    ) -> list[StoredAnalyticsSyncRun]:
        async for session in self._database.session(tenant_id):
            rows = (
                await session.scalars(
                    select(AnalyticsSyncRun)
                    .where(AnalyticsSyncRun.shop_id == shop_id)
                    .order_by(AnalyticsSyncRun.started_at.desc())
                    .limit(limit)
                )
            ).all()
            return [
                StoredAnalyticsSyncRun(
                    id=row.id,
                    resource_type=row.resource_type,
                    status=row.status,
                    attempt_count=row.attempt_count,
                    fetched_count=row.fetched_count,
                    persisted_count=row.persisted_count,
                    error_category=row.error_category,
                    error_summary=row.error_summary,
                    fresh_at=row.last_source_updated_at,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                )
                for row in rows
            ]
        raise RuntimeError("Tenant database session was not created.")


async def _stored_video_rows(
    session, shop_id: UUID, rows
) -> list[StoredAnalyticsContent]:
    product_images = await resolve_product_images(
        session,
        shop_id,
        _promoted_product_ids(row[1] for row in rows),
    )
    video_covers = await resolve_video_covers(
        session,
        shop_id,
        (str(row[0]) for row in rows),
    )
    return [
        StoredAnalyticsContent(
            row[0],
            _with_media_images(
                _with_completion(row[1], row[6]),
                product_images,
                video_covers.get(str(row[0])),
            ),
            *row[2:6],
        )
        for row in rows
    ]


async def _stored_windowed_video_rows(
    session, shop_id: UUID, rows
) -> list[StoredAnalyticsContent]:
    product_images = await resolve_product_images(
        session,
        shop_id,
        _promoted_product_ids(row[1] for row in rows),
    )
    video_covers = await resolve_video_covers(
        session,
        shop_id,
        (str(row[0]) for row in rows),
    )
    return [
        StoredAnalyticsContent(
            row[0],
            _with_media_images(
                _with_completion(
                    merge_windowed_fields(row[1], row[2]),
                    row[7],
                ),
                product_images,
                video_covers.get(str(row[0])),
            ),
            *row[3:7],
        )
        for row in rows
    ]


def _with_completion(
    fields: dict[str, object], raw_data: dict[str, object] | None
) -> dict[str, object]:
    merged = dict(fields)
    if raw_data and raw_data.get("completion_rate") is not None:
        merged["completionRate"] = raw_data["completion_rate"]
        merged["completionSecond"] = raw_data.get("completion_second")
        stages = raw_data.get("retention_stages")
        if isinstance(stages, dict):
            for source_key, field_key in {
                "2s": "retention2sRate",
                "6s": "retention6sRate",
                "25%": "retention25Rate",
                "50%": "retention50Rate",
                "75%": "retention75Rate",
                "100%": "retention100Rate",
            }.items():
                stage = stages.get(source_key)
                if isinstance(stage, dict) and stage.get("rate") is not None:
                    merged[field_key] = stage["rate"]
    return merged


def _promoted_product_ids(
    fields_list: Iterable[dict[str, object]],
) -> set[str]:
    result: set[str] = set()
    for fields in fields_list:
        products = fields.get("promotedProducts")
        if not isinstance(products, list):
            continue
        for product in products:
            if isinstance(product, Mapping) and product.get("id") is not None:
                result.add(str(product["id"]))
    return result


def _with_media_images(
    fields: dict[str, object],
    product_images: dict[str, str],
    cover_image_url: str | None,
) -> dict[str, object]:
    merged = dict(fields)
    if cover_image_url:
        merged["coverImageUrl"] = cover_image_url
    products = merged.get("promotedProducts")
    if isinstance(products, list):
        merged["promotedProducts"] = [
            {
                **dict(product),
                **(
                    {"imageUrl": image_url}
                    if (
                        isinstance(product, Mapping)
                        and (product_id := product.get("id")) is not None
                        and (image_url := product_images.get(str(product_id)))
                    )
                    else {}
                ),
            }
            if isinstance(product, Mapping)
            else product
            for product in products
        ]
    return merged
