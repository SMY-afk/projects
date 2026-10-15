from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from erp_api.models.affiliate_creator import (
    AffiliateCreator,
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.services.affiliate_center_read_queries import (
    CREATOR_SORTS,
    CreatorSort,
    SortOrder,
)
from erp_api.services.affiliate_center_summary import (
    CREATOR_SUMMARY_FIELDS,
    empty_creator_summary,
)
from erp_api.services.affiliate_creator_avatar_query import (
    video_avatars_for_usernames,
)
from erp_api.services.affiliate_creator_read_models import (
    creator_metric_dict,
    creator_report_dict,
)
from erp_api.services.affiliate_creator_window_coverage import (
    select_complete_creator_windows,
)
from erp_api.services.affiliate_daily_queries import (
    split_bounded_queries,
    split_compass_queries,
    split_daily_queries,
)
from erp_api.services.affiliate_metric_parse_support import creator_username_key

_ADDITIVE_COLUMNS = (
    "affiliate_gmv_minor",
    "affiliate_live_gmv_minor",
    "affiliate_video_gmv_minor",
    "affiliate_showcase_gmv_minor",
    "affiliate_product_items_sold",
    "items_sold",
    "estimated_commission_minor",
    "estimated_flat_fee_minor",
    "showcase_product_count",
    "affiliate_order_count",
    "product_impressions",
    "average_affiliate_customers",
    "affiliate_live_count",
    "affiliate_video_count",
    "target_collaboration_gmv_minor",
    "target_collaboration_estimated_commission_minor",
    "open_collaboration_gmv_minor",
    "open_collaboration_estimated_commission_minor",
    "refunded_affiliate_gmv_minor",
    "refunded_affiliate_product_count",
)


async def aggregated_creator_page(
    session,
    tenant_id: UUID,
    query,
    *,
    page: int,
    page_size: int,
    sort: CreatorSort,
    order: SortOrder,
) -> dict[str, object] | None:
    reports = (
        await session.execute(
            select(AffiliateCreatorReport)
            .where(
                AffiliateCreatorReport.tenant_id == tenant_id,
                AffiliateCreatorReport.shop_id == query.shop_id,
                AffiliateCreatorReport.period_start >= query.window_start,
                AffiliateCreatorReport.period_end <= query.window_end,
                AffiliateCreatorReport.shop_timezone == query.shop_timezone,
                AffiliateCreatorReport.currency == query.currency,
                AffiliateCreatorReport.status == "complete",
            )
            .order_by(
                AffiliateCreatorReport.period_start.asc(),
                AffiliateCreatorReport.period_end.asc(),
                AffiliateCreatorReport.captured_at.desc(),
                AffiliateCreatorReport.revision_no.desc(),
            )
        )
    ).scalars()
    reports_by_window = {}
    for report in reports:
        reports_by_window.setdefault((report.period_start, report.period_end), report)
    components = split_bounded_queries(query, max_days=30)
    component_keys = [(item.window_start, item.window_end) for item in components]
    if any(key not in reports_by_window for key in component_keys):
        components = split_compass_queries(query)
        component_keys = [(item.window_start, item.window_end) for item in components]
    if any(key not in reports_by_window for key in component_keys):
        components = split_daily_queries(query)
        component_keys = [(item.window_start, item.window_end) for item in components]
    if any(key not in reports_by_window for key in component_keys):
        selected_reports = select_complete_creator_windows(
            reports_by_window, query.window_start, query.window_end
        )
        if selected_reports is None:
            return None
    else:
        selected_reports = [reports_by_window[key] for key in component_keys]
    rows = (
        await session.execute(
            select(
                AffiliateCreator,
                AffiliateCreatorMetric,
                AffiliateCreatorReport.period_start,
                AffiliateCreatorReport.captured_at,
            )
            .join(
                AffiliateCreatorMetric,
                (AffiliateCreatorMetric.creator_id == AffiliateCreator.id)
                & (AffiliateCreatorMetric.tenant_id == AffiliateCreator.tenant_id)
                & (AffiliateCreatorMetric.shop_id == AffiliateCreator.shop_id),
            )
            .join(
                AffiliateCreatorReport,
                AffiliateCreatorReport.id == AffiliateCreatorMetric.report_id,
            )
            .where(
                AffiliateCreatorMetric.tenant_id == tenant_id,
                AffiliateCreatorMetric.shop_id == query.shop_id,
                AffiliateCreatorMetric.report_id.in_(
                    [report.id for report in selected_reports]
                ),
            )
        )
    ).all()
    aggregated = aggregate_creator_rows(rows)
    ordered = _sort_rows(aggregated, sort, order)
    offset = (page - 1) * page_size
    current_page = ordered[offset : offset + page_size]
    video_avatars = await _fallback_avatars(
        session,
        tenant_id,
        query.shop_id,
        current_page,
    )
    return {
        "report": _combined_report(query, selected_reports, len(aggregated)),
        "items": [
            creator_metric_dict(
                creator,
                metric,
                fallback_avatar_url=video_avatars.get(creator.username_normalized),
            )
            for creator, metric in current_page
        ],
        "page": page,
        "pageSize": page_size,
        "total": len(aggregated),
        "summary": _summary(aggregated),
        "sort": sort,
        "order": order,
    }


def aggregate_creator_rows(rows: Iterable[tuple]) -> list[tuple[object, object]]:
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        username = row[0].username_normalized or row[0].username
        grouped.setdefault(creator_username_key(username), []).append(row)
    result = []
    for creator_rows in grouped.values():
        latest = max(creator_rows, key=lambda row: (row[2], row[3]))
        data = {
            column.name: getattr(latest[1], column.name, None)
            for column in AffiliateCreatorMetric.__table__.columns
        }
        for field in _ADDITIVE_COLUMNS:
            data[field] = _sum_field(creator_rows, field)
        data["average_order_amount_minor"] = _integer_ratio(
            data["affiliate_gmv_minor"],
            data["affiliate_order_count"],
        )
        data["click_through_rate"] = _weighted_rate(
            creator_rows,
            "click_through_rate",
            "product_impressions",
        )
        result.append((latest[0], SimpleNamespace(**data)))
    return result


def _sort_rows(rows, sort: CreatorSort, order: SortOrder):
    field = CREATOR_SORTS[sort].name

    def value(row):
        raw = row[0].username if sort == "username" else getattr(row[1], field, None)
        if raw is None:
            return None
        return str(raw).casefold() if sort == "username" else _decimal(raw)

    present = [row for row in rows if value(row) is not None]
    missing = [row for row in rows if value(row) is None]
    present.sort(key=lambda row: row[0].username.casefold())
    present.sort(key=value, reverse=order == "desc")
    missing.sort(key=lambda row: row[0].username.casefold())
    return present + missing


async def _fallback_avatars(session, tenant_id, shop_id, rows):
    usernames = {
        creator.username_normalized
        for creator, _metric in rows
        if not creator.avatar_url and creator.username_normalized
    }
    if not usernames:
        return {}
    result = await session.execute(
        video_avatars_for_usernames(tenant_id, shop_id, usernames)
    )
    return dict(result.all())


def _combined_report(query, reports, row_count):
    latest = max(reports, key=lambda report: report.captured_at)
    result = creator_report_dict(latest)
    window_start, window_end = query.utc_window()
    result.update(
        scopeLabel=f"{query.window_start} - {query.window_end}",
        windowStart=query.window_start,
        windowEnd=query.window_end,
        windowStartUtc=window_start,
        windowEndUtc=window_end,
        sourceKind="daily_aggregate"
        if all(report.period_start == report.period_end for report in reports)
        else "window_aggregate",
        sourceMetadata={"componentReportCount": len(reports)},
        rowCount=row_count,
        capturedAt=max(report.captured_at for report in reports),
    )
    return result


def _summary(rows):
    result = empty_creator_summary()
    result["creatorCount"] = len(rows)
    for _creator, metric in rows:
        for output_field, column in CREATOR_SUMMARY_FIELDS.items():
            value = _decimal(getattr(metric, column.name, None))
            if value is not None:
                result[output_field] += int(value)
    return result


def _sum_field(rows, field):
    values = [_decimal(getattr(row[1], field, None)) for row in rows]
    present = [value for value in values if value is not None]
    if not present:
        return None
    total = sum(present, Decimal(0))
    return total if field == "average_affiliate_customers" else int(total)


def _weighted_rate(rows, value_field, weight_field):
    weighted = Decimal(0)
    total_weight = Decimal(0)
    for row in rows:
        value = _decimal(getattr(row[1], value_field, None))
        weight = _decimal(getattr(row[1], weight_field, None))
        if value is None or weight is None or weight <= 0:
            continue
        weighted += value * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return format((weighted / total_weight).normalize(), "f")


def _integer_ratio(numerator, denominator):
    first, second = _decimal(numerator), _decimal(denominator)
    if first is None or second is None or second <= 0:
        return None
    return int((first / second).quantize(Decimal(1)))


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
