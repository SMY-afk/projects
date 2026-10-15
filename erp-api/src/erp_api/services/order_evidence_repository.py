from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp_api.models.order import Order
from erp_api.models.order_conversion_link import OrderConversionLink
from erp_api.models.order_line import OrderLine
from erp_api.models.scraped_data import ScrapedData
from erp_api.services.affiliate_evidence_mapping import build_affiliate_evidence
from erp_api.services.order_attribution_merger import (
    OrderEvidence,
    merge_order_evidence,
)
from erp_api.services.order_attribution_repository import OrderAttributionRepository


@dataclass(frozen=True)
class EvidenceIngestResult:
    evidence_count: int
    attribution_count: int
    unmatched_count: int


class OrderEvidenceRepository:
    """Persist source evidence and recalculate the current order decision."""

    def __init__(self) -> None:
        self._attribution_repository = OrderAttributionRepository()

    async def ingest_affiliate_records(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> EvidenceIngestResult:
        evidence = [build_affiliate_evidence(record) for record in records]
        return await self._ingest(session, tenant_id, shop_id, evidence)

    async def ingest_seller_records(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> EvidenceIngestResult:
        return await self._ingest(session, tenant_id, shop_id, list(records))

    async def _ingest(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        shop_id: UUID,
        evidence: list[Mapping[str, object]],
    ) -> EvidenceIngestResult:
        if not evidence:
            return EvidenceIngestResult(0, 0, 0)
        main_order_ids = {
            str(item["main_order_id"]) for item in evidence if item.get("main_order_id")
        }
        orders = (
            await session.scalars(
                select(Order).where(
                    Order.shop_id == shop_id,
                    Order.platform_order_id.in_(main_order_ids),
                )
            )
        ).all()
        orders_by_platform_id = {item.platform_order_id: item for item in orders}
        touched_order_ids: set[UUID] = set()
        evidence_count = 0
        unmatched_count = 0

        for item in evidence:
            order = orders_by_platform_id.get(str(item.get("main_order_id") or ""))
            if order is None:
                unmatched_count += 1
                continue
            order_line_id = await _resolve_order_line_id(session, order.id, item)
            link = await self._persist_link(
                session,
                tenant_id,
                order.id,
                order_line_id,
                item,
            )
            touched_order_ids.add(order.id)
            evidence_count += int(link is not None)

        await session.flush()
        for order_id in touched_order_ids:
            links = (
                await session.scalars(
                    select(OrderConversionLink).where(
                        OrderConversionLink.tenant_id == tenant_id,
                        OrderConversionLink.order_id == order_id,
                    )
                )
            ).all()
            decision = merge_order_evidence([_to_evidence(item) for item in links])
            await self._attribution_repository.upsert(
                session,
                tenant_id,
                order_id,
                decision,
            )
        return EvidenceIngestResult(
            evidence_count, len(touched_order_ids), unmatched_count
        )

    async def _persist_link(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        order_line_id: UUID | None,
        item: Mapping[str, object],
    ) -> OrderConversionLink:
        source_system = _required_text(item, "source_system")
        source_record_key = _required_text(item, "source_record_key")
        external_conversion_id = _required_text(item, "external_conversion_id")
        evidence_hash = _evidence_hash(item)
        current = await session.scalar(
            select(OrderConversionLink).where(
                OrderConversionLink.tenant_id == tenant_id,
                OrderConversionLink.order_id == order_id,
                OrderConversionLink.source_system == source_system,
                OrderConversionLink.external_conversion_id == external_conversion_id,
                OrderConversionLink.evidence_hash == evidence_hash,
            )
        )
        if current is not None:
            return current
        raw_platform_id = _optional_text(item, "raw_platform_id")
        scraped_data_id = None
        if raw_platform_id:
            scraped_data_id = await session.scalar(
                select(ScrapedData.id).where(ScrapedData.platform_id == raw_platform_id)
            )
        link = OrderConversionLink(
            tenant_id=tenant_id,
            order_id=order_id,
            order_line_id=order_line_id,
            scraped_data_id=scraped_data_id,
            source_system=source_system,
            source_record_key=source_record_key,
            external_conversion_id=external_conversion_id,
            match_key_type=_optional_text(item, "match_key_type"),
            match_key_value=_optional_text(item, "match_key_value"),
            creator_external_id=_optional_text(item, "creator_external_id"),
            video_external_id=_optional_text(item, "video_external_id"),
            live_external_id=_optional_text(item, "live_external_id"),
            product_external_id=_optional_text(item, "product_external_id"),
            sku_external_id=_optional_text(item, "sku_external_id"),
            campaign_external_id=_optional_text(item, "campaign_external_id"),
            promotion_external_id=_optional_text(item, "promotion_external_id"),
            traffic_source_candidate=_optional_text(item, "traffic_source_candidate"),
            operator_subject_candidate=_optional_text(
                item, "operator_subject_candidate"
            ),
            entry_point_candidate=_optional_text(item, "entry_point_candidate"),
            evidence_strength=_required_text(item, "evidence_strength"),
            confidence_score=float(item.get("confidence_score") or 0),
            evidence_json=_mapping_or_none(item.get("evidence_json")),
            evidence_hash=evidence_hash,
            source_created_at=_datetime_or_none(item.get("source_created_at")),
            source_updated_at=_datetime_or_none(item.get("source_updated_at")),
        )
        session.add(link)
        await session.flush()
        return link


async def _resolve_order_line_id(
    session: AsyncSession,
    order_id: UUID,
    item: Mapping[str, object],
) -> UUID | None:
    platform_line_id = _optional_text(item, "platform_order_line_id")
    if platform_line_id:
        return await session.scalar(
            select(OrderLine.id).where(
                OrderLine.order_id == order_id,
                OrderLine.platform_line_id == platform_line_id,
            )
        )
    sku_id = _optional_text(item, "sku_external_id")
    product_id = _optional_text(item, "product_external_id")
    if not sku_id or not product_id:
        return None
    candidates = (
        await session.scalars(
            select(OrderLine.id).where(
                OrderLine.order_id == order_id,
                OrderLine.platform_product_id == product_id,
                OrderLine.platform_sku_id == sku_id,
            )
        )
    ).all()
    return candidates[0] if len(candidates) == 1 else None


def _to_evidence(link: OrderConversionLink) -> OrderEvidence:
    return OrderEvidence(
        link_id=link.id,
        order_line_id=link.order_line_id,
        source_system=link.source_system,
        source_record_key=link.source_record_key,
        external_conversion_id=link.external_conversion_id,
        match_key_type=link.match_key_type,
        match_key_value=link.match_key_value,
        creator_external_id=link.creator_external_id,
        video_external_id=link.video_external_id,
        live_external_id=link.live_external_id,
        product_external_id=link.product_external_id,
        sku_external_id=link.sku_external_id,
        campaign_external_id=link.campaign_external_id,
        promotion_external_id=link.promotion_external_id,
        traffic_source=link.traffic_source_candidate,
        operator_subject=link.operator_subject_candidate,
        entry_point=link.entry_point_candidate,
        evidence_strength=link.evidence_strength,
        confidence_score=float(link.confidence_score),
        source_updated_at=link.source_updated_at,
        evidence=link.evidence_json,
    )


def _evidence_hash(item: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(item: Mapping[str, object], key: str) -> str:
    value = _optional_text(item, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(item: Mapping[str, object], key: str) -> str | None:
    return _optional_scalar_text(item.get(key))


def _optional_scalar_text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None


def _mapping_or_none(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
