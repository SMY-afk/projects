from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import (
    AffiliateCreatorMetricDTO,
    AffiliateVideoMetricDTO,
)

AffiliateMetricDTO = AffiliateCreatorMetricDTO | AffiliateVideoMetricDTO
AffiliateSourceKind = Literal["page_capture", "browser_export", "official_api"]
AffiliatePaginationMode = Literal[
    "page_page_size", "offset", "cursor", "mixed", "unknown"
]


@dataclass(frozen=True)
class AffiliatePaginationDTO:
    mode: AffiliatePaginationMode
    page_number: int | None = None
    page_size: int | None = None
    offset: int | None = None
    next_cursor: str | None = None
    has_more: bool | None = None
    total_count: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {
            "page_page_size",
            "offset",
            "cursor",
            "mixed",
            "unknown",
        }:
            raise ValueError("Unsupported affiliate pagination mode.")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("page_number must be positive.")
        if self.page_size is not None and self.page_size < 1:
            raise ValueError("page_size must be positive.")
        if self.offset is not None and self.offset < 0:
            raise ValueError("offset cannot be negative.")
        if self.total_count is not None and self.total_count < 0:
            raise ValueError("total_count cannot be negative.")
        if self.next_cursor is not None:
            cursor = self.next_cursor.strip()
            object.__setattr__(self, "next_cursor", cursor or None)


@dataclass(frozen=True)
class AffiliateSourcePageContext:
    request_id: str
    pagination_mode: AffiliatePaginationMode
    page_number: int | None = None
    page_size: int | None = None
    offset: int | None = None
    next_cursor: str | None = None
    has_more: bool | None = None
    total_count: int | None = None
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        request_id = self.request_id.strip()
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must contain 1 to 128 characters.")
        object.__setattr__(self, "request_id", request_id)
        if self.source_updated_at is not None:
            if self.source_updated_at.tzinfo is None:
                raise ValueError("source_updated_at must be timezone-aware.")
            object.__setattr__(
                self,
                "source_updated_at",
                self.source_updated_at.astimezone(UTC),
            )

    def pagination(self) -> AffiliatePaginationDTO:
        return AffiliatePaginationDTO(
            mode=self.pagination_mode,
            page_number=self.page_number,
            page_size=self.page_size,
            offset=self.offset,
            next_cursor=self.next_cursor,
            has_more=self.has_more,
            total_count=self.total_count,
        )


@dataclass(frozen=True)
class AffiliateCenterPageDTO:
    source_kind: AffiliateSourceKind
    query: AffiliateCenterQuery
    records: tuple[AffiliateMetricDTO, ...]
    pagination: AffiliatePaginationDTO
    request_id: str
    source_updated_at: datetime | None
    raw_payload: dict[str, object]

    def __post_init__(self) -> None:
        if self.source_kind not in {"page_capture", "browser_export", "official_api"}:
            raise ValueError("Unsupported affiliate source kind.")
        expected_type = (
            AffiliateCreatorMetricDTO
            if self.resource is AffiliateCenterResource.CREATORS
            else AffiliateVideoMetricDTO
        )
        if any(not isinstance(record, expected_type) for record in self.records):
            raise ValueError("Page records do not match the query resource.")
        request_id = self.request_id.strip()
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must contain 1 to 128 characters.")
        object.__setattr__(self, "request_id", request_id)
        if self.source_updated_at is not None:
            if self.source_updated_at.tzinfo is None:
                raise ValueError("source_updated_at must be timezone-aware.")
            object.__setattr__(
                self,
                "source_updated_at",
                self.source_updated_at.astimezone(UTC),
            )

    @property
    def resource(self) -> AffiliateCenterResource:
        return self.query.resource

    @property
    def raw_payload_kind(self) -> str:
        resource = (
            "creator" if self.resource is AffiliateCenterResource.CREATORS else "video"
        )
        if self.source_kind == "browser_export":
            return f"affiliate_{resource}_export"
        return f"affiliate_{resource}_page"


@runtime_checkable
class AffiliateCenterSource(Protocol):
    source_kind: AffiliateSourceKind

    def iter_pages(
        self,
        query: AffiliateCenterQuery,
        *,
        start_cursor: str | None = None,
    ) -> AsyncIterator[AffiliateCenterPageDTO]: ...
