from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field

from erp_api.models.order_attribution import OrderAttribution


class AttributionEvidenceResponse(BaseModel):
    source: str
    fieldPath: str
    value: str
    strength: str
    reason: str
    reasonLabel: str


class OrderAttributionSummaryResponse(BaseModel):
    trafficSource: str
    operatorSubject: str
    entryPoint: str
    specialOrderType: str
    chainCode: str
    classificationStatus: str
    creatorExternalId: str | None = None
    creatorHandle: str | None = None
    creatorAlias: str | None = None


class OrderAttributionResponse(OrderAttributionSummaryResponse):
    classificationMethod: str
    sourceUpdatedAt: datetime | None
    confidenceScore: float = 0
    videoExternalId: str | None = None
    liveExternalId: str | None = None
    productExternalId: str | None = None
    skuExternalId: str | None = None
    campaignExternalId: str | None = None
    promotionExternalId: str | None = None
    isMultiTouch: bool = False
    conflictFlags: dict[str, Any] | None = None
    evidenceSummary: list[AttributionEvidenceResponse] = Field(default_factory=list)


def to_attribution_response(
    attribution: OrderAttribution | None,
) -> OrderAttributionResponse:
    if attribution is None:
        return OrderAttributionResponse(
            trafficSource="unknown",
            operatorSubject="unknown",
            entryPoint="unknown",
            specialOrderType="unknown",
            chainCode="unknown",
            classificationStatus="unknown",
            classificationMethod="shop_order_detail",
            sourceUpdatedAt=None,
            confidenceScore=0,
            evidenceSummary=[],
        )
    evidence = (
        attribution.evidence_json if isinstance(attribution.evidence_json, dict) else {}
    )
    return OrderAttributionResponse(
        trafficSource=attribution.traffic_source,
        operatorSubject=attribution.operator_subject,
        entryPoint=attribution.entry_point,
        specialOrderType=attribution.special_order_type,
        chainCode=attribution.chain_code,
        classificationStatus=attribution.classification_status,
        classificationMethod=attribution.classification_method,
        sourceUpdatedAt=attribution.source_updated_at,
        confidenceScore=float(attribution.confidence_score or 0),
        creatorExternalId=attribution.creator_external_id,
        creatorHandle=_text(evidence.get("creator_handle")),
        creatorAlias=_text(evidence.get("creator_alias")),
        videoExternalId=attribution.video_external_id,
        liveExternalId=attribution.live_external_id,
        productExternalId=attribution.product_external_id,
        skuExternalId=attribution.sku_external_id,
        campaignExternalId=attribution.campaign_external_id,
        promotionExternalId=attribution.promotion_external_id,
        isMultiTouch=bool(attribution.is_multi_touch),
        conflictFlags=attribution.conflict_flags,
        evidenceSummary=_evidence_summary(evidence),
    )


def to_attribution_summary_response(
    attribution: OrderAttribution | None,
) -> OrderAttributionSummaryResponse:
    full = to_attribution_response(attribution)
    return OrderAttributionSummaryResponse(
        trafficSource=full.trafficSource,
        operatorSubject=full.operatorSubject,
        entryPoint=full.entryPoint,
        specialOrderType=full.specialOrderType,
        chainCode=full.chainCode,
        classificationStatus=full.classificationStatus,
        creatorExternalId=full.creatorExternalId,
        creatorHandle=full.creatorHandle,
        creatorAlias=full.creatorAlias,
    )


def _evidence_summary(value: dict[str, object]) -> list[AttributionEvidenceResponse]:
    source = _text(value.get("source"))
    strength = _text(value.get("strength"))
    reason = _text(value.get("reason"))
    if not source or not strength or not reason:
        return []

    field_path = _text(value.get("field_path"))
    safe_value = _safe_value(value.get("value"))
    if not field_path and _text(value.get("match_key_type")):
        field_path = f"{source}.{_text(value.get('match_key_type'))}"
        safe_value = _fingerprint(
            value.get("external_conversion_id") or value.get("match_key")
        )
    if not field_path or not safe_value:
        return []
    return [
        AttributionEvidenceResponse(
            source=source,
            fieldPath=field_path,
            value=safe_value,
            strength=strength,
            reason=reason,
            reasonLabel=_reason_label(reason),
        )
    ]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_value(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    safe_values = {
        "missing",
        "true",
        "false",
        "missing_order_level_key",
        "conflict",
        "organic",
        "paid_ads",
        "creator",
        "self_operated",
        "mall",
        "video",
        "live",
        "offsite",
        "showcase",
        "affiliate_product_page",
        "search_recommendation",
        "normal",
        "sample",
        "purchase_sample_rebate",
        "unknown",
    }
    if text in safe_values:
        return text
    return _fingerprint(text)


def _fingerprint(value: object) -> str:
    raw = _text(value) or "missing"
    return f"sha256:{sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _reason_label(reason: str) -> str:
    return {
        "missing_platform_field": "未识别：订单详情未返回来源字段",
        "unsupported_endpoint": "未识别：平台不支持该来源字段",
        "platform_no_order_level_evidence": "平台无订单级证据",
        "conflicting_signals": "未识别：订单级证据冲突",
        "stale_signal": "未识别：订单级证据已过期",
        "validated_seller_center_label": "未识别：仅有汇总标签，缺少订单级证据",
    }.get(reason, reason)
