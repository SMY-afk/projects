from typing import Literal, cast

AnalyticsContentResourceType = Literal["video", "live"]
AnalyticsSyncResourceType = Literal[
    "video",
    "live",
    "affiliate_creator",
    "affiliate_video",
    "affiliate_creator_detail",
]

ARQ_OFFICIAL_RESOURCE_TYPES = frozenset({"video", "live"})


def require_arq_official_resource(
    resource_type: str,
    source_kind: str,
) -> AnalyticsContentResourceType:
    if source_kind == "page_capture":
        raise ValueError("Browser-backed affiliate capture is capture-daemon-owned.")
    if source_kind != "official_api":
        raise ValueError("ARQ sync source must be official_api.")
    if resource_type not in ARQ_OFFICIAL_RESOURCE_TYPES:
        raise ValueError("No ARQ official API source is configured for this resource.")
    return cast(AnalyticsContentResourceType, resource_type)
