"""Validate an original TikTok XLSX export before any RDS write."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.parsers.affiliate_creator_export_parser import parse_affiliate_creator_export
from app.parsers.affiliate_video_export_parser import parse_affiliate_video_export
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import AffiliateSourcePageContext
from erp_api.services.affiliate_center_source_adapters import (
    map_browser_export_creator_page,
    map_browser_export_video_page,
)

MAX_EXPORT_BYTES = 25 * 1024 * 1024


class RemoteAffiliateExportManifest(BaseModel):
    capture_id: UUID
    shop_id: UUID
    platform_shop_id: str = Field(min_length=1, max_length=128)
    environment_id: str = Field(pattern=r"^\d{6,20}$")
    resource: str = Field(pattern=r"^(creators|videos)$")
    window_start: date
    window_end: date
    observed_at: datetime
    request_id: str = Field(min_length=1, max_length=128)
    source_total: int = Field(ge=0, le=200_000)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("window_end")
    @classmethod
    def require_window(cls, value: date, info) -> date:
        if (start := info.data.get("window_start")) is not None and value < start:
            raise ValueError("Affiliate export window is invalid")
        return value

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Affiliate export observation needs a timezone")
        return value.astimezone(UTC)


def map_validated_export(
    manifest: RemoteAffiliateExportManifest,
    content: bytes,
    query: AffiliateCenterQuery,
):
    if not content.startswith(b"PK\x03\x04") or len(content) > MAX_EXPORT_BYTES:
        raise ValueError("Affiliate export must be a bounded XLSX file")
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest.file_sha256:
        raise ValueError("Affiliate export digest changed")
    if (
        query.resource.value != manifest.resource
        or query.shop_id != manifest.shop_id
        or query.window_start != manifest.window_start
        or query.window_end != manifest.window_end
    ):
        raise ValueError("Affiliate export query does not match its manifest")
    context = AffiliateSourcePageContext(
        request_id=manifest.request_id,
        pagination_mode="unknown",
        page_number=1,
        has_more=False,
        total_count=manifest.source_total,
        source_updated_at=manifest.observed_at,
    )
    raw = {
        "export": {
            "format": "xlsx",
            "fileSha256": digest,
            "recordCount": manifest.source_total,
            "source": "remote_hubstudio_export",
        }
    }
    if query.resource is AffiliateCenterResource.CREATORS:
        rows = parse_affiliate_creator_export(content, query.currency)
        page = map_browser_export_creator_page(
            query, rows, context=context, raw_payload=raw
        )
        unique = {record.username_normalized for record in page.records}
        if len(unique) != manifest.source_total:
            raise ValueError("Affiliate creator export differs from source total")
    else:
        rows = parse_affiliate_video_export(
            content, query.currency, query.shop_timezone
        )
        page = map_browser_export_video_page(
            query, rows, context=context, raw_payload=raw
        )
        unique = {record.video_id for record in page.records}
        if len(rows) != manifest.source_total:
            raise ValueError("Affiliate video export differs from source total")
    return page, {
        "expected_total": manifest.source_total,
        "pages_fetched": 1,
        "records_received": len(rows),
        "records_unique": len(unique),
        "duplicates": len(rows) - len(unique),
    }
