from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from erp_api.services.order_chain_classifier import OrderAttributionDecision


@dataclass(frozen=True)
class OrderEvidence:
    source_system: str
    source_record_key: str
    external_conversion_id: str
    match_key_type: str | None
    match_key_value: str | None
    evidence_strength: str
    confidence_score: float
    link_id: UUID | None = None
    order_line_id: UUID | None = None
    creator_external_id: str | None = None
    video_external_id: str | None = None
    live_external_id: str | None = None
    product_external_id: str | None = None
    sku_external_id: str | None = None
    campaign_external_id: str | None = None
    promotion_external_id: str | None = None
    traffic_source: str | None = None
    operator_subject: str | None = None
    entry_point: str | None = None
    source_updated_at: datetime | None = None
    evidence: dict[str, object] | None = None

    @property
    def has_order_key(self) -> bool:
        return bool(
            self.match_key_value
            and self.match_key_type in {"order_id", "order_item_id"}
        )


_STRENGTH_RANK = {
    "aggregate_only": 0,
    "identity_only": 20,
    "content_bridge": 70,
    "exact_order": 90,
    "exact_order_line": 100,
}


def merge_order_evidence(evidence: list[OrderEvidence]) -> OrderAttributionDecision:
    candidates = _latest_order_evidence(evidence)
    if not candidates:
        return _empty_decision()

    conflict_flags = _conflicts(candidates)
    if conflict_flags:
        return _conflict_decision(candidates, conflict_flags)

    winner = max(candidates, key=_winner_key)
    operator_subject = winner.operator_subject or (
        "creator" if winner.creator_external_id else "unknown"
    )
    entry_point = _entry_point(winner)
    traffic_source = winner.traffic_source or "unknown"
    chain_code = (
        f"{traffic_source}.{operator_subject}.{entry_point}"
        if "unknown" not in {traffic_source, operator_subject, entry_point}
        else "unknown"
    )
    is_confirmed_content = (
        entry_point == "video" and bool(winner.video_external_id)
    ) or (entry_point == "live" and bool(winner.live_external_id))
    has_attribution = bool(
        winner.creator_external_id
        or winner.video_external_id
        or winner.live_external_id
        or entry_point != "unknown"
    )
    status = (
        "confirmed"
        if is_confirmed_content
        else "derived"
        if has_attribution
        else "unknown"
    )
    summary = _summary(candidates)
    return OrderAttributionDecision(
        traffic_source=traffic_source,
        operator_subject=operator_subject,
        entry_point=entry_point,
        special_order_type="unknown",
        chain_code=chain_code,
        classification_status=status,
        classification_method="evidence_merge",
        evidence={
            "source": winner.source_system,
            "match_key_type": winner.match_key_type or "missing",
            "match_key": winner.match_key_value or "missing",
            "external_conversion_id": winner.external_conversion_id,
            "strength": winner.evidence_strength,
            "reason": "exact_order_link",
            **_display_identity(winner),
        },
        source_updated_at=_newest_timestamp(candidates),
        creator_external_id=winner.creator_external_id,
        campaign_external_id=winner.campaign_external_id,
        video_external_id=winner.video_external_id,
        live_external_id=winner.live_external_id,
        product_external_id=winner.product_external_id,
        sku_external_id=winner.sku_external_id,
        promotion_external_id=winner.promotion_external_id,
        confidence_score=winner.confidence_score,
        winning_evidence_link_id=winner.link_id,
        is_multi_touch=len(candidates) > 1,
        evidence_summary=summary,
    )


def _latest_order_evidence(evidence: list[OrderEvidence]) -> list[OrderEvidence]:
    latest: dict[tuple[str, str], OrderEvidence] = {}
    for item in evidence:
        if not item.has_order_key or item.evidence_strength == "aggregate_only":
            continue
        key = (item.source_system, item.source_record_key)
        current = latest.get(key)
        if current is None or _winner_key(item) > _winner_key(current):
            latest[key] = item
    return list(latest.values())


def _winner_key(item: OrderEvidence) -> tuple[int, int, float, float]:
    return (
        _attribution_rank(item),
        _STRENGTH_RANK.get(item.evidence_strength, 0),
        item.confidence_score,
        item.source_updated_at.timestamp() if item.source_updated_at else float("-inf"),
    )


def _attribution_rank(item: OrderEvidence) -> int:
    if item.video_external_id or item.live_external_id:
        return 3
    if item.creator_external_id:
        return 2
    if _entry_point(item) != "unknown" or item.traffic_source:
        return 1
    return 0


def _entry_point(item: OrderEvidence) -> str:
    if item.video_external_id:
        return "video"
    if item.live_external_id:
        return "live"
    return item.entry_point or "unknown"


def _conflicts(evidence: list[OrderEvidence]) -> dict[str, object]:
    strong = [item for item in evidence if item.confidence_score >= 0.8]
    dimensions = {
        "creator": {
            item.creator_external_id for item in strong if item.creator_external_id
        },
        "entry_point": {
            _entry_point(item) for item in strong if _entry_point(item) != "unknown"
        },
        "traffic_source": {
            item.traffic_source for item in strong if item.traffic_source
        },
    }
    return {
        name: sorted(values) for name, values in dimensions.items() if len(values) > 1
    }


def _conflict_decision(
    evidence: list[OrderEvidence], conflict_flags: dict[str, object]
) -> OrderAttributionDecision:
    return OrderAttributionDecision(
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="conflict",
        classification_method="evidence_merge",
        evidence={
            "source": "order_conversion_links",
            "field_path": "evidence_candidates",
            "value": "conflict",
            "strength": "strong",
            "reason": "conflicting_signals",
        },
        source_updated_at=_newest_timestamp(evidence),
        confidence_score=max(item.confidence_score for item in evidence),
        is_multi_touch=True,
        conflict_flags=conflict_flags,
        evidence_summary=_summary(evidence),
    )


def _empty_decision() -> OrderAttributionDecision:
    return OrderAttributionDecision(
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="evidence_merge",
        evidence={
            "source": "order_conversion_links",
            "field_path": "match_key",
            "value": "missing_order_level_key",
            "strength": "unsupported",
            "reason": "platform_no_order_level_evidence",
        },
        confidence_score=0,
        evidence_summary={"evidence_count": 0, "sources": []},
    )


def _summary(evidence: list[OrderEvidence]) -> dict[str, object]:
    return {
        "evidence_count": len(evidence),
        "sources": sorted({item.source_system for item in evidence}),
        "order_line_count": len(
            {item.order_line_id for item in evidence if item.order_line_id}
        ),
        "product_ids": sorted(
            {item.product_external_id for item in evidence if item.product_external_id}
        ),
        "sku_ids": sorted(
            {item.sku_external_id for item in evidence if item.sku_external_id}
        ),
    }


def _display_identity(evidence: OrderEvidence) -> dict[str, str]:
    details = evidence.evidence or {}
    handle = details.get("creator_handle")
    alias = details.get("creator_alias")
    return {
        **({"creator_handle": handle} if isinstance(handle, str) and handle else {}),
        **({"creator_alias": alias} if isinstance(alias, str) and alias else {}),
    }


def _newest_timestamp(evidence: list[OrderEvidence]) -> datetime | None:
    values = [item.source_updated_at for item in evidence if item.source_updated_at]
    return max(values) if values else None
