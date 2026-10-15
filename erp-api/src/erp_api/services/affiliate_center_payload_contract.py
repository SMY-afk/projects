from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

CREATOR_PAYLOAD_DISCRIMINATOR = "tiktok_affiliate_creator_filter_list.v1"
VIDEO_PAYLOAD_DISCRIMINATOR = "tiktok_affiliate_video_detail_list.v1"

_PAGE_KEYS = frozenset(
    {"page", "pageindex", "pagenum", "pagesize", "nextpage", "totalpage"}
)
_OFFSET_KEYS = frozenset({"offset"})
_CURSOR_KEYS = frozenset({"cursor", "nextcursor"})
_PAGINATION_EVIDENCE_KEYS = frozenset(
    _PAGE_KEYS | _OFFSET_KEYS | _CURSOR_KEYS | {"hasmore", "limit", "total"}
)


class AffiliatePayloadDiscriminatorError(ValueError):
    pass


def require_affiliate_payload(resource: str, payload: object) -> str:
    if resource == "creators" and _is_creator_payload(payload):
        return CREATOR_PAYLOAD_DISCRIMINATOR
    if resource == "videos" and _is_video_payload(payload):
        return VIDEO_PAYLOAD_DISCRIMINATOR
    if resource not in {"creators", "videos"}:
        raise AffiliatePayloadDiscriminatorError("Unknown affiliate resource.")
    raise AffiliatePayloadDiscriminatorError(
        "Response payload does not match the expected affiliate resource."
    )


def is_creator_identity_only_payload(payload: object) -> bool:
    data = _valid_envelope_data(payload)
    if data is None:
        return False
    segments = data.get("segments")
    if not _non_empty_list(segments):
        return False
    identity_found = False
    for segment in segments:
        if not isinstance(segment, Mapping):
            return False
        timed_lists = segment.get("timed_lists")
        if not _non_empty_list(timed_lists):
            return False
        for timed_list in timed_lists:
            if not isinstance(timed_list, Mapping):
                return False
            stats = timed_list.get("stats")
            if not isinstance(stats, list):
                return False
            for stat in stats:
                if not _mapping_has(stat, {"id", "handle"}):
                    return False
                assert isinstance(stat, Mapping)
                if set(stat) != {"id", "handle"}:
                    return False
                identity_found = True
    return identity_found


def classify_pagination_mode(field_paths: Iterable[str]) -> dict[str, object]:
    evidence: list[str] = []
    families: set[str] = set()
    for path in sorted(set(field_paths)):
        leaf = _normalize_key(path.rsplit(".", 1)[-1].removesuffix("[]"))
        if leaf in _PAGINATION_EVIDENCE_KEYS:
            evidence.append(path)
        if leaf in _PAGE_KEYS:
            families.add("page_page_size")
        if leaf in _OFFSET_KEYS:
            families.add("offset")
        if leaf in _CURSOR_KEYS:
            families.add("cursor")

    if len(families) > 1:
        mode = "mixed"
    elif families:
        mode = next(iter(families))
    else:
        mode = "unknown"
    return {
        "mode": mode,
        "basis": "observed_field_names",
        "requestPaginationObserved": False,
        "families": sorted(families),
        "evidenceFields": evidence,
    }


def _is_creator_payload(payload: object) -> bool:
    data = _valid_envelope_data(payload)
    if data is None:
        return False
    segments = data.get("segments")
    return _non_empty_list(segments) and all(
        _is_creator_segment(item) for item in segments
    )


def _is_creator_segment(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    creator_filter = value.get("filter")
    list_control = value.get("list_control")
    descriptor = value.get("time_descriptor")
    timed_lists = value.get("timed_lists")
    if not (
        _mapping_has(creator_filter, {"shop_id"})
        and _mapping_has(list_control, {"next_pagination", "rules"})
        and _mapping_has(descriptor, {"start", "end", "timezone_offset"})
        and _non_empty_list(timed_lists)
    ):
        return False
    assert isinstance(list_control, Mapping)
    pagination = list_control["next_pagination"]
    if not (
        _mapping_has(pagination, {"has_more", "next_page", "total", "total_page"})
        and isinstance(list_control["rules"], list)
    ):
        return False
    return all(_is_creator_timed_list(item) for item in timed_lists)


def _is_creator_timed_list(value: object) -> bool:
    if not _mapping_has(value, {"start", "end", "stats"}):
        return False
    assert isinstance(value, Mapping)
    stats = value["stats"]
    return isinstance(stats, list) and all(_is_creator_stat(item) for item in stats)


def _is_creator_stat(value: object) -> bool:
    if not _mapping_has(value, {"id", "handle", "revenue", "order_cnt"}):
        return False
    assert isinstance(value, Mapping)
    return _mapping_has(value["revenue"], {"amount", "currency_code"})


def _is_video_payload(payload: object) -> bool:
    data = _valid_envelope_data(payload)
    if data is None:
        return False
    segments = data.get("video_list_segments_v2")
    return _non_empty_list(segments) and all(
        _is_video_segment(item) for item in segments
    )


def _is_video_segment(value: object) -> bool:
    if not _mapping_has(value, {"time_descriptor", "total"}):
        return False
    assert isinstance(value, Mapping)
    descriptor = value["time_descriptor"]
    performances = value.get("video_performances")
    empty_without_rows = (
        "video_performances" not in value
        and type(value["total"]) is int
        and value["total"] == 0
    )
    return (
        _mapping_has(descriptor, {"start_time", "end_time", "timezone_offset"})
        and (
            empty_without_rows
            or (
                isinstance(performances, list)
                and all(_is_video_performance(item) for item in performances)
            )
        )
    )


def _is_video_performance(value: object) -> bool:
    if not _mapping_has(
        value,
        {
            "creator_base",
            "product_base_list",
            "product_ids",
            "video_info",
            "video_metrics",
        },
    ):
        return False
    assert isinstance(value, Mapping)
    creator = value["creator_base"]
    video = value["video_info"]
    metrics = value["video_metrics"]
    return (
        _mapping_has(creator, {"oec_id", "handle_name"})
        and _mapping_has(video, {"item_id", "create_time"})
        and _mapping_has(
            metrics,
            {
                "video_gmv",
                "video_orders_cnt",
                "video_product_impressions_cnt",
                "video_views_cnt",
            },
        )
        and isinstance(value["product_base_list"], list)
        and isinstance(value["product_ids"], list)
    )


def _valid_envelope_data(payload: object) -> Mapping[str, object] | None:
    if not _mapping_has(payload, {"code", "message", "data"}):
        return None
    assert isinstance(payload, Mapping)
    data = payload["data"]
    return data if isinstance(data, Mapping) else None


def _mapping_has(value: object, keys: set[str]) -> bool:
    return isinstance(value, Mapping) and keys.issubset(value)


def _non_empty_list(value: object) -> bool:
    return isinstance(value, list) and bool(value)


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())
