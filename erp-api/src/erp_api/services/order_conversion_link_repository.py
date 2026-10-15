from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp_api.db.tenant_scope import TenantContextError, require_tenant_id
from erp_api.models.order_conversion_link import OrderConversionLink
from erp_api.services.tiktok_ads_order_schemas import TikTokAdsOrderSignal
from erp_api.services.tiktok_affiliate_order_schemas import TikTokAffiliateOrderSignal


class OrderConversionLinkRepository:
    """Persist exact external conversion links in the caller-owned transaction."""

    async def upsert_affiliate(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        signal: TikTokAffiliateOrderSignal,
    ) -> OrderConversionLink:
        self._validate_session_tenant(session, tenant_id)
        evidence_hash = _evidence_hash(signal)
        link = await session.scalar(
            select(OrderConversionLink).where(
                OrderConversionLink.tenant_id == tenant_id,
                OrderConversionLink.order_id == order_id,
                OrderConversionLink.source_system == "affiliate_order",
                OrderConversionLink.external_conversion_id
                == signal.external_conversion_id,
                OrderConversionLink.evidence_hash == evidence_hash,
            )
        )
        if link is None:
            link = OrderConversionLink(
                tenant_id=tenant_id,
                order_id=order_id,
                source_system="affiliate_order",
                source_record_key=signal.external_conversion_id,
                external_conversion_id=signal.external_conversion_id,
                match_key_type=signal.match_key_type,
                match_key_value=signal.match_key,
                creator_external_id=signal.creator_external_id,
                traffic_source_candidate=signal.traffic_source,
                operator_subject_candidate=(
                    signal.operator_subject
                    or ("creator" if signal.creator_external_id else None)
                ),
                entry_point_candidate=signal.entry_point,
                evidence_strength=(
                    "exact_order_line"
                    if signal.match_key_type == "order_item_id"
                    else "exact_order"
                ),
                confidence_score=0.95,
                evidence_json=signal.evidence,
                evidence_hash=evidence_hash,
                source_updated_at=signal.source_updated_at,
                observed_at=signal.source_updated_at or datetime.now(UTC),
            )
            session.add(link)
        await session.flush()
        return link

    async def upsert_ads(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        signal: TikTokAdsOrderSignal,
    ) -> OrderConversionLink:
        self._validate_session_tenant(session, tenant_id)
        evidence_hash = _ads_evidence_hash(signal)
        link = await session.scalar(
            select(OrderConversionLink).where(
                OrderConversionLink.tenant_id == tenant_id,
                OrderConversionLink.order_id == order_id,
                OrderConversionLink.source_system == "ads_order",
                OrderConversionLink.external_conversion_id
                == signal.external_conversion_id,
                OrderConversionLink.evidence_hash == evidence_hash,
            )
        )
        if link is None:
            link = OrderConversionLink(
                tenant_id=tenant_id,
                order_id=order_id,
                source_system="ads_order",
                source_record_key=signal.external_conversion_id,
                external_conversion_id=signal.external_conversion_id,
                match_key_type=signal.match_key_type,
                match_key_value=signal.match_key,
                campaign_external_id=signal.campaign_external_id,
                traffic_source_candidate=signal.traffic_source,
                operator_subject_candidate=signal.operator_subject,
                entry_point_candidate=signal.entry_point,
                evidence_strength=(
                    "exact_order_line"
                    if signal.match_key_type == "order_item_id"
                    else "exact_order"
                ),
                confidence_score=0.95,
                evidence_json=signal.evidence,
                evidence_hash=evidence_hash,
                source_updated_at=signal.source_updated_at,
                observed_at=signal.source_updated_at or datetime.now(UTC),
            )
            session.add(link)
        await session.flush()
        return link

    @staticmethod
    def _validate_session_tenant(session: AsyncSession, tenant_id: UUID) -> None:
        require_tenant_id(tenant_id)
        if (
            session.info.get("system_scope") is not True
            and session.info.get("tenant_id") != tenant_id
        ):
            raise TenantContextError(
                "The database session tenant does not match the requested tenant."
            )


def _evidence_hash(signal: TikTokAffiliateOrderSignal) -> str:
    payload = {
        "external_conversion_id": signal.external_conversion_id,
        "match_key_type": signal.match_key_type,
        "match_key": signal.match_key,
        "creator_external_id": signal.creator_external_id,
        "traffic_source": signal.traffic_source,
        "operator_subject": signal.operator_subject,
        "entry_point": signal.entry_point,
        "platform_source_code": signal.platform_source_code,
        "source_updated_at": signal.source_updated_at.isoformat()
        if signal.source_updated_at
        else None,
        "evidence": signal.evidence,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ads_evidence_hash(signal: TikTokAdsOrderSignal) -> str:
    payload = {
        "external_conversion_id": signal.external_conversion_id,
        "match_key_type": signal.match_key_type,
        "match_key": signal.match_key,
        "campaign_external_id": signal.campaign_external_id,
        "traffic_source": signal.traffic_source,
        "operator_subject": signal.operator_subject,
        "entry_point": signal.entry_point,
        "platform_source_code": signal.platform_source_code,
        "source_updated_at": signal.source_updated_at.isoformat()
        if signal.source_updated_at
        else None,
        "evidence": signal.evidence,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
