from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from erp_api.services.affiliate_center_metric_dtos import AffiliateVideoMetricDTO


def aggregate_official_video_creators(
    records: list[AffiliateVideoMetricDTO],
) -> list[dict[str, object]]:
    """Build creator rows from seller-owned affiliate video analytics."""
    groups: dict[str, list[AffiliateVideoMetricDTO]] = defaultdict(list)
    for record in records:
        identity = record.creator_open_id or _username(record)
        if identity:
            groups[identity].append(record)

    rows = []
    for identity, items in groups.items():
        first = items[0]
        username = _username(first) or _anonymous_username(identity)
        rows.append(
            {
                "creatorOpenId": first.creator_open_id,
                "username": username,
                "avatarUrl": first.creator_avatar_url,
                "currency": first.currency,
                "affiliateGmvMinor": _sum(items, "gmv_minor"),
                "affiliateVideoGmvMinor": _sum(items, "gmv_minor"),
                "affiliateProductItemsSold": _sum(items, "items_sold"),
                "itemsSold": _sum(items, "items_sold"),
                "affiliateOrderCount": _sum(items, "order_count"),
                "productImpressions": _sum(items, "product_impressions"),
                "affiliateVideoCount": len({item.video_id for item in items}),
                "affiliateFollowerCount": _maximum(
                    items, "creator_follower_count"
                ),
                "estimatedCommissionMinor": _sum(
                    items, "estimated_commission_minor"
                ),
            }
        )
    return sorted(
        rows,
        key=lambda row: (-(row["affiliateGmvMinor"] or 0), str(row["username"])),
    )


def _username(record: AffiliateVideoMetricDTO) -> str | None:
    return record.creator_username or record.creator_nickname


def _anonymous_username(identity: str) -> str:
    digest = sha256(identity.encode()).hexdigest()[:16]
    return f"@official_{digest}"


def _sum(items: list[AffiliateVideoMetricDTO], field: str) -> int | None:
    values = [getattr(item, field) for item in items]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _maximum(items: list[AffiliateVideoMetricDTO], field: str) -> int | None:
    values = [getattr(item, field) for item in items]
    present = [value for value in values if value is not None]
    return max(present) if present else None
