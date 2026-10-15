from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AffiliatePartialReason = Literal[
    "total_count_mismatch",
    "cursor_interrupted",
    "page_failed",
]


@dataclass(frozen=True)
class AffiliateCreatorReportCompletion:
    expected_total: int | None
    pages_fetched: int
    records_received: int
    records_unique: int
    duplicate_count: int
    completeness_reason: str

    def __post_init__(self) -> None:
        counts = (
            self.pages_fetched,
            self.records_received,
            self.records_unique,
            self.duplicate_count,
        )
        if self.expected_total is not None and self.expected_total < 0:
            raise ValueError("expected_total cannot be negative.")
        if any(value < 0 for value in counts):
            raise ValueError("Report completion counts cannot be negative.")
        if self.completeness_reason != "complete":
            raise ValueError("Only a complete capture can complete a report.")
        if (
            self.expected_total is not None
            and self.records_unique != self.expected_total
        ):
            raise ValueError("Unique records must match expected_total.")


@dataclass(frozen=True)
class AffiliateCreatorReportPartial:
    expected_total: int | None
    pages_fetched: int
    records_received: int
    records_unique: int
    duplicate_count: int
    completeness_reason: AffiliatePartialReason

    def __post_init__(self) -> None:
        counts = (
            self.pages_fetched,
            self.records_received,
            self.records_unique,
            self.duplicate_count,
        )
        if self.expected_total is not None and self.expected_total < 0:
            raise ValueError("expected_total cannot be negative.")
        if any(value < 0 for value in counts):
            raise ValueError("Report partial counts cannot be negative.")


def apply_creator_report_completion(report, run, completion) -> None:
    if run.resource_type != "affiliate_creator":
        raise RuntimeError(
            "Creator report completion requires an affiliate creator run."
        )
    if report is None:
        raise RuntimeError("Affiliate creator report was not found.")
    if report.tenant_id != run.tenant_id or report.shop_id != run.shop_id:
        raise RuntimeError("Affiliate creator report does not belong to the sync run.")
    if report.status != "running":
        raise RuntimeError("Affiliate creator report is not running.")
    report.status = "complete"
    report.expected_total = completion.expected_total
    report.pages_fetched = completion.pages_fetched
    report.records_received = completion.records_received
    report.records_unique = completion.records_unique
    report.duplicate_count = completion.duplicate_count
    report.completeness_reason = completion.completeness_reason


def apply_creator_report_partial(report, run, partial) -> None:
    if run.resource_type != "affiliate_creator":
        raise RuntimeError("Creator report partial requires an affiliate creator run.")
    if report is None:
        raise RuntimeError("Affiliate creator report was not found.")
    if report.tenant_id != run.tenant_id or report.shop_id != run.shop_id:
        raise RuntimeError("Affiliate creator report does not belong to the sync run.")
    if report.status != "running":
        raise RuntimeError("Affiliate creator report is not running.")
    report.status = "partial"
    report.expected_total = partial.expected_total
    report.pages_fetched = partial.pages_fetched
    report.records_received = partial.records_received
    report.records_unique = partial.records_unique
    report.duplicate_count = partial.duplicate_count
    report.completeness_reason = partial.completeness_reason
