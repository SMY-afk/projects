from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.video_performance_snapshot import (
    TikTokVideoPerformanceSnapshot,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem
from erp_api.services.video_performance_fields import (
    ACCOUNT_TYPES,
    CONTENT_FIELD_NAMES,
)

PERFORMANCE_UPSERT_BATCH_SIZE = 300


class VideoPerformanceRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert_page(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        sync_run_id: UUID,
        items: list[TikTokAnalyticsItem],
        *,
        window_start: datetime,
        window_end: datetime,
        currency: str,
        account_type: str,
        external_id_field: str,
        platform_request_id: str | None,
    ) -> int:
        rows = _performance_rows(
            tenant_id,
            shop_id,
            sync_run_id,
            items,
            window_start=window_start,
            window_end=window_end,
            currency=currency,
            account_type=account_type,
            external_id_field=external_id_field,
            platform_request_id=platform_request_id,
        )
        if not rows:
            return 0
        async for session in self._database.session(tenant_id):
            for batch in _batches(rows):
                statement = insert(TikTokVideoPerformanceSnapshot).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_tiktok_video_performance_run_video",
                    set_={
                        "metrics": statement.excluded.metrics,
                        "source_updated_at": statement.excluded.source_updated_at,
                        "platform_request_id": statement.excluded.platform_request_id,
                        "captured_at": datetime.now(UTC),
                    },
                )
                await session.execute(statement)
            await session.commit()
            return len(rows)
        raise RuntimeError("Tenant database session was not created.")


def _performance_rows(
    tenant_id: UUID,
    shop_id: UUID,
    sync_run_id: UUID,
    items: list[TikTokAnalyticsItem],
    *,
    window_start: datetime,
    window_end: datetime,
    currency: str,
    account_type: str,
    external_id_field: str,
    platform_request_id: str | None,
) -> list[dict[str, object]]:
    start = _utc(window_start, "window_start")
    end = _utc(window_end, "window_end")
    if end <= start:
        raise ValueError("window_end must be later than window_start.")
    normalized_currency = currency.upper()
    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        raise ValueError("currency must be a three-letter code.")
    if account_type not in ACCOUNT_TYPES:
        raise ValueError("Unsupported video analytics account_type.")
    if not external_id_field:
        raise ValueError("external_id_field is required.")
    rows: dict[str, dict[str, object]] = {}
    excluded_fields = CONTENT_FIELD_NAMES | {external_id_field}
    for item in items:
        external_id = item.fields.get(external_id_field)
        if not isinstance(external_id, str) or not external_id:
            raise ValueError(f"Analytics item is missing string {external_id_field!r}.")
        rows[external_id] = {
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "sync_run_id": sync_run_id,
            "platform_video_id": external_id[:128],
            "window_start": start,
            "window_end": end,
            "currency": normalized_currency,
            "account_type": account_type,
            "metrics": {
                key: value
                for key, value in item.fields.items()
                if key not in excluded_fields
            },
            "source_updated_at": (
                None
                if item.source_updated_at is None
                else _utc(item.source_updated_at, "source_updated_at")
            ),
            "platform_request_id": (
                platform_request_id[:128] if platform_request_id else None
            ),
        }
    return list(rows.values())


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset.")
    return value.astimezone(UTC)


def _batches(rows: list[dict[str, object]]):
    for index in range(0, len(rows), PERFORMANCE_UPSERT_BATCH_SIZE):
        yield rows[index : index + PERFORMANCE_UPSERT_BATCH_SIZE]
