"""Fail-closed contract for a complete browser affiliate capture."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from erp_api.services.affiliate_center_source import AffiliateCenterPageDTO


class RemoteAffiliatePage(BaseModel):
    page_number: int = Field(ge=1, le=200)
    next_page_number: int | None = Field(default=None, ge=2, le=201)
    request_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    payload: dict[str, object]
    observation: dict[str, object]

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Affiliate observation needs a timezone")
        return value.astimezone(UTC)


class RemoteAffiliateBatch(BaseModel):
    capture_id: UUID
    shop_id: UUID
    platform_shop_id: str = Field(min_length=1, max_length=128)
    environment_id: str = Field(pattern=r"^\d{6,20}$")
    resource: str = Field(pattern=r"^(creators|videos)$")
    window_start: date
    window_end: date
    pages: list[RemoteAffiliatePage] = Field(min_length=1, max_length=200)

    @field_validator("window_end")
    @classmethod
    def require_valid_window(cls, value: date, info) -> date:
        start = info.data.get("window_start")
        if start is not None and value < start:
            raise ValueError("Affiliate window end precedes start")
        return value


def validate_mapped_batch(
    batch: RemoteAffiliateBatch, pages: list[AffiliateCenterPageDTO]
) -> dict[str, int]:
    if len(pages) != len(batch.pages):
        raise ValueError("Affiliate page count changed during validation")
    if batch.pages[-1].next_page_number is not None:
        raise ValueError("Affiliate terminal page is not confirmed")
    seen_requests: set[str] = set()
    seen_records: set[str] = set()
    totals: set[int] = set()
    records_received = 0
    for index, (source, mapped) in enumerate(zip(batch.pages, pages, strict=True), 1):
        expected_next = index + 1 if index < len(pages) else None
        if source.page_number != index or source.next_page_number != expected_next:
            raise ValueError("Affiliate pagination must be contiguous")
        if (
            mapped.query.shop_id != batch.shop_id
            or mapped.resource.value != batch.resource
            or mapped.query.window_start != batch.window_start
            or mapped.query.window_end != batch.window_end
        ):
            raise ValueError("Affiliate mapped query does not match the batch")
        if (
            mapped.pagination.page_number != index
            or mapped.pagination.has_more != (expected_next is not None)
            or mapped.pagination.next_cursor
            != (f"page:{expected_next}" if expected_next else None)
            or mapped.request_id != source.request_id
        ):
            raise ValueError("Affiliate mapped pagination differs from the source")
        if source.request_id in seen_requests:
            raise ValueError("Affiliate request ID was repeated")
        seen_requests.add(source.request_id)
        if mapped.pagination.total_count is not None:
            totals.add(mapped.pagination.total_count)
        for record in mapped.records:
            key = (
                record.creator_open_id or record.username_normalized
                if batch.resource == "creators"
                else record.video_id
            )
            if not key:
                raise ValueError("Affiliate record identity is missing")
            seen_records.add(key)
            records_received += 1
    if len(totals) != 1 or next(iter(totals)) != len(seen_records):
        raise ValueError("Affiliate captured total differs from unique records")
    return {
        "expected_total": next(iter(totals)),
        "pages_fetched": len(pages),
        "records_received": records_received,
        "records_unique": len(seen_records),
        "duplicates": records_received - len(seen_records),
    }
