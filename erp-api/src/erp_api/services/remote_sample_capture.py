"""Validate a complete local RAW capture before any server-side write."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.hubstudio_sample_response_parser import (
    parse_hubstudio_sample_response,
)
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)


class RemoteSamplePage(BaseModel):
    payload: dict
    request_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("RAW sample observation needs a timezone")
        return value.astimezone(UTC)


class RemoteSampleBatch(BaseModel):
    sample_type: Literal["free", "refundable"] = "free"
    capture_id: UUID
    shop_id: UUID
    environment_id: str = Field(pattern=r"^\d{6,20}$")
    platform_shop_id: str = Field(min_length=1, max_length=128)
    pages: list[RemoteSamplePage] = Field(min_length=1, max_length=500)


def parse_complete_batch(
    batch: RemoteSampleBatch,
) -> tuple[tuple[TikTokSampleApplicationPage, ...], str | None]:
    parsed = tuple(
        parse_hubstudio_sample_response(
            item.payload,
            platform_request_id=item.request_id,
            observed_at=item.observed_at,
        )
        for item in batch.pages
    )
    for index, (raw, page) in enumerate(zip(batch.pages, parsed, strict=True), 1):
        refundable = "refundable_response" in raw.payload
        if refundable != (batch.sample_type == "refundable"):
            raise ValueError("RAW sample batch type does not match its source")
        if refundable and raw.payload["refundable_request"]["cur_page"] != index:
            raise ValueError("Refundable pages are missing, duplicated or out of order")
        if any(item.get("sample_type", "free") != batch.sample_type for item in page.applications):
            raise ValueError("RAW sample application type conflicts with its batch")
    if batch.sample_type == "refundable" and len({
        page.payload["refundable_request"]["tab_type"] for page in batch.pages
    }) != 1:
        raise ValueError("Refundable status scopes must not share a batch")
    if parsed[-1].next_page_token is not None:
        raise ValueError("RAW sample terminal page is not confirmed")
    if any(page.next_page_token is None for page in parsed[:-1]):
        raise ValueError("RAW sample pagination ended before the final page")
    totals = {page.total_count for page in parsed if page.total_count is not None}
    if len(totals) > 1:
        raise ValueError("RAW sample expected total changed")
    unique_ids = {str(item["id"]) for page in parsed for item in page.applications}
    if totals and next(iter(totals)) != len(unique_ids):
        raise ValueError("RAW sample captured total differs from expected total")
    digest = hashlib.sha256()
    for page in parsed:
        for application in page.applications:
            sanitized = sanitize_capture_payload(application)
            digest.update(
                json.dumps(
                    sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            )
    return parsed, digest.hexdigest() if unique_ids else None
