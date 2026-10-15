from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from erp_api.services.external_order_evidence import (
    PLATFORM_NO_ORDER_LEVEL_EVIDENCE,
    UNSUPPORTED_ENDPOINT,
)
from erp_api.services.tiktok_ads_order_schemas import TikTokAdsOrderSignal
from erp_api.services.tiktok_affiliate_order_schemas import TikTokAffiliateOrderSignal
from erp_api.services.tiktok_order_schemas import TikTokOrderAttributionSignal


@dataclass(frozen=True)
class OrderAttributionDecision:
    """A pure classification result suitable for persistence or API mapping."""

    traffic_source: str
    operator_subject: str
    entry_point: str
    special_order_type: str
    chain_code: str
    classification_status: str
    classification_method: str
    evidence: dict[str, str]
    source_updated_at: datetime | None = None
    creator_external_id: str | None = None
    platform_source_code: str | None = None
    campaign_external_id: str | None = None
    video_external_id: str | None = None
    live_external_id: str | None = None
    product_external_id: str | None = None
    sku_external_id: str | None = None
    promotion_external_id: str | None = None
    confidence_score: float = 0
    winning_evidence_link_id: UUID | None = None
    is_multi_touch: bool = False
    conflict_flags: dict[str, object] | None = None
    evidence_summary: dict[str, object] | None = None
    resolution_version: int = 1


class OrderChainClassifier:
    """Classify only from verified order-level platform signals.

    The current step-0 mapping exposes ``is_sample_order`` but does not expose
    the source, operator, entry point, or sample subtype needed for a
    confirmed chain. Consequently every current decision is ``unknown`` while
    retaining the available signal as evidence. The classifier has no I/O and
    never mutates its input.
    """

    @staticmethod
    def classify(
        signal: TikTokOrderAttributionSignal | None,
        affiliate_signal: TikTokAffiliateOrderSignal | None = None,
        ads_signal: TikTokAdsOrderSignal | None = None,
        external_evidence_absence_reason: str | None = None,
    ) -> OrderAttributionDecision:
        affiliate_signal = affiliate_signal if _valid_signal(affiliate_signal) else None
        ads_signal = ads_signal if _valid_signal(ads_signal) else None
        if affiliate_signal is not None and ads_signal is not None:
            if _signals_conflict(affiliate_signal, ads_signal):
                timestamps = [
                    value
                    for value in (
                        affiliate_signal.source_updated_at,
                        ads_signal.source_updated_at,
                    )
                    if value is not None
                ]
                return _conflicting_decision(
                    source_updated_at=max(timestamps) if timestamps else None
                )
            return _classify_ads(ads_signal)
        if ads_signal is not None:
            return _classify_ads(ads_signal)
        if affiliate_signal is not None:
            return _classify_affiliate(affiliate_signal)
        if external_evidence_absence_reason == PLATFORM_NO_ORDER_LEVEL_EVIDENCE:
            return _no_order_level_evidence_decision(
                source_updated_at=signal.source_updated_at if signal else None
            )
        if external_evidence_absence_reason == UNSUPPORTED_ENDPOINT:
            return _unsupported_endpoint_decision(
                source_updated_at=signal.source_updated_at if signal else None
            )
        if signal is None:
            return _unknown_decision(
                evidence={
                    "source": "shop_order_detail",
                    "field_path": "data.orders[].is_sample_order",
                    "value": "missing",
                    "strength": "unsupported",
                    "reason": "missing_platform_field",
                },
                source_updated_at=None,
            )

        sample_value = signal.is_sample_order
        evidence = {
            "source": "shop_order_detail",
            "field_path": "data.orders[].is_sample_order",
            "value": _signal_value(sample_value),
            "strength": "medium" if sample_value is not None else "unsupported",
            "reason": "missing_platform_field",
        }
        return _unknown_decision(
            evidence=evidence,
            source_updated_at=signal.source_updated_at,
        )


_TRAFFIC_SOURCES = frozenset({"organic", "paid_ads", "unknown"})
_OPERATORS = frozenset({"creator", "self_operated", "mall", "unknown"})
_ENTRY_POINTS = frozenset(
    {
        "video",
        "live",
        "offsite",
        "showcase",
        "affiliate_product_page",
        "search_recommendation",
        "unknown",
    }
)


def _allowlisted(value: str | None, allowed: frozenset[str]) -> str:
    return value if value in allowed else "unknown"


def _unknown_decision(
    *, evidence: dict[str, str], source_updated_at: datetime | None
) -> OrderAttributionDecision:
    return OrderAttributionDecision(
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="shop_order_detail",
        evidence=evidence,
        source_updated_at=source_updated_at,
    )


def _no_order_level_evidence_decision(
    *,
    source_updated_at: datetime | None,
) -> OrderAttributionDecision:
    return _unknown_decision(
        evidence={
            "source": "external_order_evidence",
            "field_path": "affiliate_order|ads_order",
            "value": "missing_order_level_key",
            "strength": "unsupported",
            "reason": PLATFORM_NO_ORDER_LEVEL_EVIDENCE,
        },
        source_updated_at=source_updated_at,
    )


def _unsupported_endpoint_decision(
    *,
    source_updated_at: datetime | None,
) -> OrderAttributionDecision:
    return _unknown_decision(
        evidence={
            "source": "external_order_evidence",
            "field_path": "affiliate_order|ads_order",
            "value": "missing",
            "strength": "unsupported",
            "reason": UNSUPPORTED_ENDPOINT,
        },
        source_updated_at=source_updated_at,
    )


def _classify_affiliate(signal: TikTokAffiliateOrderSignal) -> OrderAttributionDecision:
    traffic_source = _allowlisted(signal.traffic_source, _TRAFFIC_SOURCES)
    raw_operator = signal.operator_subject or (
        "creator" if signal.creator_external_id else "unknown"
    )
    operator_subject = _allowlisted(raw_operator, _OPERATORS)
    entry_point = _allowlisted(signal.entry_point, _ENTRY_POINTS)
    has_creator_evidence = bool(
        signal.creator_external_id and operator_subject == "creator"
    )
    dimensions_complete = all(
        value != "unknown" for value in (traffic_source, operator_subject, entry_point)
    )
    classification_status = (
        "confirmed"
        if dimensions_complete and has_creator_evidence
        else "derived"
        if dimensions_complete or has_creator_evidence
        else "unknown"
    )
    chain_code = (
        f"{traffic_source}.{operator_subject}.{entry_point}"
        if traffic_source != "unknown"
        and operator_subject != "unknown"
        and entry_point != "unknown"
        else "unknown"
    )
    evidence = {
        "source": "affiliate_order",
        "match_key_type": signal.match_key_type,
        "match_key": signal.match_key,
        "external_conversion_id": signal.external_conversion_id,
        "strength": "strong",
        "reason": "exact_order_link",
        **(signal.evidence or {}),
    }
    return OrderAttributionDecision(
        traffic_source=traffic_source,
        operator_subject=operator_subject,
        entry_point=entry_point,
        special_order_type="unknown",
        chain_code=chain_code,
        classification_status=classification_status,
        classification_method="affiliate_order",
        evidence=evidence,
        source_updated_at=signal.source_updated_at,
        creator_external_id=signal.creator_external_id,
        platform_source_code=signal.platform_source_code,
        confidence_score=0.9 if has_creator_evidence else 0.5,
    )


def _classify_ads(signal: TikTokAdsOrderSignal) -> OrderAttributionDecision:
    traffic_source = _allowlisted(signal.traffic_source, _TRAFFIC_SOURCES)
    operator_subject = _allowlisted(signal.operator_subject, _OPERATORS)
    entry_point = _allowlisted(signal.entry_point, _ENTRY_POINTS)
    dimensions_complete = all(
        value != "unknown" for value in (traffic_source, operator_subject, entry_point)
    )
    chain_code = (
        f"{traffic_source}.{operator_subject}.{entry_point}"
        if dimensions_complete
        else "unknown"
    )
    evidence = {
        "source": "ads_order",
        "match_key_type": signal.match_key_type,
        "match_key": signal.match_key,
        "external_conversion_id": signal.external_conversion_id,
        "strength": "strong",
        "reason": "exact_order_link",
        **(signal.evidence or {}),
    }
    return OrderAttributionDecision(
        traffic_source=traffic_source,
        operator_subject=operator_subject,
        entry_point=entry_point,
        special_order_type="unknown",
        chain_code=chain_code,
        classification_status="derived" if dimensions_complete else "unknown",
        classification_method="ads_order_link",
        evidence=evidence,
        source_updated_at=signal.source_updated_at,
        platform_source_code=signal.platform_source_code,
        campaign_external_id=signal.campaign_external_id,
    )


def _signals_conflict(
    affiliate_signal: TikTokAffiliateOrderSignal,
    ads_signal: TikTokAdsOrderSignal,
) -> bool:
    dimensions = (
        (affiliate_signal.traffic_source, ads_signal.traffic_source),
        (affiliate_signal.operator_subject, ads_signal.operator_subject),
        (affiliate_signal.entry_point, ads_signal.entry_point),
    )
    return any(left and right and left != right for left, right in dimensions)


def _valid_signal(signal: object) -> bool:
    return bool(getattr(signal, "has_exact_match", False))


def _conflicting_decision(
    *, source_updated_at: datetime | None
) -> OrderAttributionDecision:
    return _unknown_decision(
        evidence={
            "source": "order_level_external_links",
            "field_path": "affiliate_order|ads_order",
            "value": "conflict",
            "strength": "strong",
            "reason": "conflicting_signals",
        },
        source_updated_at=source_updated_at,
    )


def _signal_value(value: bool | None) -> str:
    if value is None:
        return "missing"
    return "true" if value else "false"
