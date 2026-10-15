from __future__ import annotations

from erp_api.models.affiliate_creator import AffiliateCreatorMetric
from erp_api.services.affiliate_center_contract import AffiliateCenterResource


def creator_report_dict(report, *, duplicate: bool = False) -> dict[str, object]:
    return {
        "id": report.id,
        "resource": AffiliateCenterResource.CREATORS.value,
        "scopeLabel": report.scope_label,
        "shopId": report.shop_id,
        "windowStart": report.period_start,
        "windowEnd": report.period_end,
        "windowStartUtc": report.window_start_utc,
        "windowEndUtc": report.window_end_utc,
        "shopTimezone": report.shop_timezone,
        "currency": report.currency,
        "filters": report.filters,
        "sourceKind": report.source_kind,
        "sourceMetadata": report.source_metadata,
        "revisionNo": report.revision_no,
        "status": report.status,
        "completenessReason": report.completeness_reason,
        "rowCount": report.records_unique,
        "capturedAt": report.captured_at,
        "duplicate": duplicate,
    }


def creator_metric_dict(
    creator,
    metric,
    *,
    fallback_avatar_url: str | None = None,
) -> dict[str, object]:
    excluded = {"id", "tenant_id", "shop_id", "report_id", "creator_id"}
    data = {
        _camel_case(column.name): getattr(metric, column.name)
        for column in AffiliateCreatorMetric.__table__.columns
        if column.name not in excluded
    }
    data.update(
        id=creator.id,
        username=creator.username,
        creatorOpenId=creator.creator_open_id,
        avatarUrl=creator.avatar_url or fallback_avatar_url,
    )
    return data


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)
