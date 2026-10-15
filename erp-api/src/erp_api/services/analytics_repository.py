from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.analytics_snapshot import (
    AnalyticsSnapshot,
    TikTokLiveSession,
    TikTokVideoContent,
)
from erp_api.services.analytics_content_upsert import (
    content_batches,
    content_upsert_statement,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem

AnalyticsGranularity = Literal["day", "hour"]


@dataclass(frozen=True)
class AnalyticsSnapshotInput:
    metric_set: str
    granularity: AnalyticsGranularity
    window_start: datetime
    window_end: datetime
    currency: str
    metrics: dict[str, object]
    source_updated_at: datetime | None
    platform_request_id: str | None


@dataclass(frozen=True)
class StoredAnalyticsSnapshot:
    metric_set: str
    granularity: str
    window_start: datetime
    window_end: datetime
    currency: str
    metrics: dict[str, object]
    source_updated_at: datetime | None
    captured_at: datetime


class AnalyticsRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert_snapshots(
        self, tenant_id: UUID, shop_id: UUID, snapshots: list[AnalyticsSnapshotInput]
    ) -> int:
        rows = self._snapshot_rows(tenant_id, shop_id, snapshots)
        if not rows:
            return 0
        statement = insert(AnalyticsSnapshot).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="uq_analytics_snapshots_shop_metric_window_currency",
            set_={
                "metrics": AnalyticsSnapshot.metrics.op("||")(
                    statement.excluded.metrics
                ),
                "source_updated_at": statement.excluded.source_updated_at,
                "platform_request_id": statement.excluded.platform_request_id,
                "captured_at": datetime.now(UTC),
            },
        )
        async for session in self._database.session(tenant_id):
            await session.execute(statement)
            await session.commit()
            return len(rows)
        raise RuntimeError("Tenant database session was not created.")

    async def list_snapshots(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        metric_set: str,
        granularity: AnalyticsGranularity,
        window_start: datetime,
        window_end: datetime,
        currency: str,
    ) -> list[StoredAnalyticsSnapshot]:
        start = _utc(window_start, "window_start")
        end = _utc(window_end, "window_end")
        if end <= start:
            raise ValueError("window_end must be later than window_start.")
        async for session in self._database.session(tenant_id):
            rows = (
                await session.scalars(
                    select(AnalyticsSnapshot)
                    .where(
                        AnalyticsSnapshot.shop_id == shop_id,
                        AnalyticsSnapshot.metric_set == _metric_set(metric_set),
                        AnalyticsSnapshot.granularity == granularity,
                        AnalyticsSnapshot.currency == _currency(currency),
                        AnalyticsSnapshot.window_start >= start,
                        AnalyticsSnapshot.window_end <= end,
                    )
                    .order_by(AnalyticsSnapshot.window_start)
                )
            ).all()
            return [
                StoredAnalyticsSnapshot(
                    metric_set=row.metric_set,
                    granularity=row.granularity,
                    window_start=row.window_start,
                    window_end=row.window_end,
                    currency=row.currency,
                    metrics=row.metrics,
                    source_updated_at=row.source_updated_at,
                    captured_at=row.captured_at,
                )
                for row in rows
            ]
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_video_contents(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        items: list[TikTokAnalyticsItem],
        *,
        external_id_field: str,
        platform_request_id: str | None,
        preserve_existing_details: bool = False,
    ) -> int:
        return await self._upsert_content_items(
            tenant_id,
            shop_id,
            items,
            model=TikTokVideoContent,
            external_id_column="platform_video_id",
            constraint="uq_tiktok_video_contents_shop_platform_video",
            external_id_field=external_id_field,
            platform_request_id=platform_request_id,
            preserve_existing_details=preserve_existing_details,
        )

    async def upsert_live_sessions(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        items: list[TikTokAnalyticsItem],
        *,
        external_id_field: str,
        platform_request_id: str | None,
    ) -> int:
        return await self._upsert_content_items(
            tenant_id,
            shop_id,
            items,
            model=TikTokLiveSession,
            external_id_column="platform_live_id",
            constraint="uq_tiktok_live_sessions_shop_platform_live",
            external_id_field=external_id_field,
            platform_request_id=platform_request_id,
        )

    async def _upsert_content_items(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        items: list[TikTokAnalyticsItem],
        *,
        model,
        external_id_column: str,
        constraint: str,
        external_id_field: str,
        platform_request_id: str | None,
        preserve_existing_details: bool = False,
    ) -> int:
        request_id = platform_request_id.strip() if platform_request_id else None
        rows = _content_rows(
            tenant_id,
            shop_id,
            items,
            external_id_column=external_id_column,
            external_id_field=external_id_field,
            platform_request_id=request_id,
        )
        if rows and not request_id:
            raise ValueError(
                "platform_request_id is required when storing analytics content."
            )
        if not rows:
            return 0
        async for session in self._database.session(tenant_id):
            for batch in content_batches(rows):
                statement = content_upsert_statement(
                    model,
                    batch,
                    constraint=constraint,
                    preserve_existing_details=preserve_existing_details,
                )
                await session.execute(statement)
            await session.commit()
            return len(rows)
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _snapshot_rows(
        tenant_id: UUID, shop_id: UUID, snapshots: list[AnalyticsSnapshotInput]
    ) -> list[dict[str, object]]:
        deduplicated: dict[
            tuple[str, str, datetime, datetime, str], dict[str, object]
        ] = {}
        for snapshot in snapshots:
            start = _utc(snapshot.window_start, "window_start")
            end = _utc(snapshot.window_end, "window_end")
            _validate_window(snapshot.granularity, start, end)
            metric_set = _metric_set(snapshot.metric_set)
            currency = _currency(snapshot.currency)
            row = {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                "metric_set": metric_set,
                "granularity": snapshot.granularity,
                "window_start": start,
                "window_end": end,
                "currency": currency,
                "metrics": dict(snapshot.metrics),
                "source_updated_at": _optional_utc(snapshot.source_updated_at),
                "platform_request_id": _bounded(snapshot.platform_request_id, 128),
            }
            deduplicated[(metric_set, snapshot.granularity, start, end, currency)] = row
        return list(deduplicated.values())


def _content_rows(
    tenant_id: UUID,
    shop_id: UUID,
    items: list[TikTokAnalyticsItem],
    *,
    external_id_column: str,
    external_id_field: str,
    platform_request_id: str | None,
) -> list[dict[str, object]]:
    if not external_id_field:
        raise ValueError("external_id_field is required.")
    deduplicated: dict[str, dict[str, object]] = {}
    for item in items:
        external_id = item.fields.get(external_id_field)
        if not isinstance(external_id, str) or not external_id:
            raise ValueError(f"Analytics item is missing string {external_id_field!r}.")
        if external_id in deduplicated:
            continue
        deduplicated[external_id] = {
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            external_id_column: _bounded(external_id, 128),
            "fields": dict(item.fields),
            "source_status": _bounded(item.source_status, 128),
            "status": _bounded(item.status, 32),
            "source_updated_at": _optional_utc(item.source_updated_at),
            "platform_request_id": _bounded(platform_request_id, 128),
        }
    return list(deduplicated.values())


def _validate_window(
    granularity: AnalyticsGranularity, start: datetime, end: datetime
) -> None:
    expected = timedelta(days=1) if granularity == "day" else timedelta(hours=1)
    if end - start != expected:
        raise ValueError(
            f"{granularity} snapshots must use exactly one {granularity} window."
        )


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset.")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value, "source_updated_at")


def _metric_set(value: str) -> str:
    if not value or len(value) > 64:
        raise ValueError("metric_set must contain 1 to 64 characters.")
    return value


def _currency(value: str) -> str:
    normalized = value.upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be a three-letter code.")
    return normalized


def _bounded(value: str | None, max_length: int) -> str | None:
    return value[:max_length] if value else None
