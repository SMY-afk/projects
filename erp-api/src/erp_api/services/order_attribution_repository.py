from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp_api.db.tenant_scope import TenantContextError, require_tenant_id
from erp_api.models.order import Order
from erp_api.models.order_attribution import OrderAttribution
from erp_api.services.order_chain_classifier import OrderAttributionDecision


class OrderAttributionOrderNotFound(LookupError):
    """Raised when an attribution is attached to a missing or other-tenant order."""


class OrderAttributionRepository:
    """Persist the current attribution inside a caller-owned tenant session.

    The repository deliberately does not commit. The order sync transaction
    owns the session and can commit the order facts and attribution together.
    """

    async def get_current(
        self, session: AsyncSession, tenant_id: UUID, order_id: UUID
    ) -> OrderAttribution | None:
        self._validate_session_tenant(session, tenant_id)
        return await session.scalar(
            select(OrderAttribution).where(
                OrderAttribution.tenant_id == tenant_id,
                OrderAttribution.order_id == order_id,
            )
        )

    async def upsert(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        decision: OrderAttributionDecision,
    ) -> OrderAttribution:
        """Insert or update the one current decision for ``order_id``.

        Older, missing-timestamp, or same-timestamp/different-hash signals do
        not overwrite a newer or potentially conflicting current decision.
        The returned model is attached to the supplied session and has been
        flushed, but the caller still controls the transaction commit.
        """

        self._validate_session_tenant(session, tenant_id)
        order_exists = await session.scalar(
            select(Order.id).where(Order.id == order_id, Order.tenant_id == tenant_id)
        )
        if order_exists is None:
            raise OrderAttributionOrderNotFound(
                "The order was not found in the tenant scope."
            )

        source_hash = _source_hash(decision)
        current = await session.scalar(
            select(OrderAttribution).where(
                OrderAttribution.tenant_id == tenant_id,
                OrderAttribution.order_id == order_id,
            )
        )
        if current is not None and _should_keep_current(current, decision, source_hash):
            return current

        if current is None:
            current = OrderAttribution(
                tenant_id=tenant_id,
                order_id=order_id,
                source_hash=source_hash,
            )
            session.add(current)

        _assign_decision(current, decision, source_hash)
        await session.flush()
        return current

    @staticmethod
    def _validate_session_tenant(session: AsyncSession, tenant_id: UUID) -> None:
        require_tenant_id(tenant_id)
        session_tenant = session.info.get("tenant_id")
        if session.info.get("system_scope") is not True and session_tenant != tenant_id:
            raise TenantContextError(
                "The database session tenant does not match the requested tenant."
            )


def _assign_decision(
    current: OrderAttribution,
    decision: OrderAttributionDecision,
    source_hash: str,
) -> None:
    current.traffic_source = decision.traffic_source
    current.operator_subject = decision.operator_subject
    current.entry_point = decision.entry_point
    current.special_order_type = decision.special_order_type
    current.chain_code = decision.chain_code
    current.classification_status = decision.classification_status
    current.classification_method = decision.classification_method
    current.platform_source_code = decision.platform_source_code
    current.creator_external_id = decision.creator_external_id
    current.video_external_id = decision.video_external_id
    current.live_external_id = decision.live_external_id
    current.product_external_id = decision.product_external_id
    current.sku_external_id = decision.sku_external_id
    current.campaign_external_id = decision.campaign_external_id
    current.promotion_external_id = decision.promotion_external_id
    current.confidence_score = decision.confidence_score
    current.winning_evidence_link_id = decision.winning_evidence_link_id
    current.is_multi_touch = decision.is_multi_touch
    current.conflict_flags = decision.conflict_flags
    current.evidence_summary = decision.evidence_summary
    current.resolution_version = decision.resolution_version
    current.evidence_json = dict(decision.evidence)
    current.source_updated_at = decision.source_updated_at
    current.source_hash = source_hash
    current.classified_at = datetime.now(UTC)


def _should_keep_current(
    current: OrderAttribution,
    decision: OrderAttributionDecision,
    source_hash: str,
) -> bool:
    current_confidence = float(current.confidence_score or 0)
    if (
        decision.classification_status == "conflict"
        and current.classification_status != "conflict"
    ):
        return False
    if (
        current.classification_status == "conflict"
        and decision.classification_status != "conflict"
    ):
        return True
    if decision.confidence_score > current_confidence:
        return False
    if decision.confidence_score < current_confidence:
        return True
    evidence_growth = _evidence_count(decision.evidence_summary) - _evidence_count(
        current.evidence_summary
    )
    if (
        current.classification_method == "evidence_merge"
        and decision.classification_method == "evidence_merge"
    ):
        if evidence_growth > 0:
            return False
        if evidence_growth < 0:
            return True
    current_updated_at = current.source_updated_at
    incoming_updated_at = decision.source_updated_at
    if current_updated_at is not None and incoming_updated_at is None:
        return True
    if (
        current_updated_at is not None
        and incoming_updated_at is not None
        and incoming_updated_at < current_updated_at
    ):
        return True
    if (
        current_updated_at is not None
        and incoming_updated_at is not None
        and incoming_updated_at == current_updated_at
        and current.source_hash != source_hash
    ):
        return True
    return current.source_hash == source_hash


def _evidence_count(summary: dict[str, object] | None) -> int:
    if not summary:
        return 0
    value = summary.get("evidence_count")
    return value if isinstance(value, int) and value >= 0 else 0


def _source_hash(decision: OrderAttributionDecision) -> str:
    payload = {
        "traffic_source": decision.traffic_source,
        "operator_subject": decision.operator_subject,
        "entry_point": decision.entry_point,
        "special_order_type": decision.special_order_type,
        "chain_code": decision.chain_code,
        "classification_status": decision.classification_status,
        "classification_method": decision.classification_method,
        "creator_external_id": decision.creator_external_id,
        "platform_source_code": decision.platform_source_code,
        "campaign_external_id": decision.campaign_external_id,
        "video_external_id": decision.video_external_id,
        "live_external_id": decision.live_external_id,
        "product_external_id": decision.product_external_id,
        "sku_external_id": decision.sku_external_id,
        "promotion_external_id": decision.promotion_external_id,
        "confidence_score": decision.confidence_score,
        "winning_evidence_link_id": (
            str(decision.winning_evidence_link_id)
            if decision.winning_evidence_link_id
            else None
        ),
        "is_multi_touch": decision.is_multi_touch,
        "conflict_flags": decision.conflict_flags,
        "evidence_summary": decision.evidence_summary,
        "resolution_version": decision.resolution_version,
        "evidence": decision.evidence,
        "source_updated_at": (
            decision.source_updated_at.isoformat()
            if decision.source_updated_at
            else None
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
