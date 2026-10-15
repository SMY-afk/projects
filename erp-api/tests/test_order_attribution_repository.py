import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.db.tenant_scope import TenantContextError
from erp_api.models.order_attribution import OrderAttribution
from erp_api.services.order_attribution_repository import (
    OrderAttributionOrderNotFound,
    OrderAttributionRepository,
)
from erp_api.services.order_chain_classifier import OrderAttributionDecision


class FakeSession:
    def __init__(self, *, order_exists=True, current=None, tenant_id=None):
        self.info = {"tenant_id": tenant_id} if tenant_id else {}
        self.order_exists = order_exists
        self.current = current
        self.added = []
        self.flushed = 0
        self.scalar_calls = 0

    async def scalar(self, statement):
        self.scalar_calls += 1
        return self.order_exists if self.scalar_calls == 1 else self.current

    def add(self, value):
        self.added.append(value)
        self.current = value

    async def flush(self):
        self.flushed += 1


def _decision(source_updated_at=None, *, marker="missing"):
    return OrderAttributionDecision(
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="shop_order_detail",
        evidence={"reason": marker},
        source_updated_at=source_updated_at,
    )


def test_upsert_inserts_and_flushes_in_the_supplied_tenant_session() -> None:
    tenant_id = uuid4()
    order_id = uuid4()
    session = FakeSession(order_exists=order_id, tenant_id=tenant_id)

    result = asyncio.run(
        OrderAttributionRepository().upsert(
            session, tenant_id, order_id, _decision(datetime(2026, 8, 13, tzinfo=UTC))
        )
    )

    assert isinstance(result, OrderAttribution)
    assert result.tenant_id == tenant_id
    assert result.order_id == order_id
    assert result.chain_code == "unknown"
    assert len(result.source_hash) == 64
    assert session.added == [result]
    assert session.flushed == 1


def test_upsert_updates_current_decision_when_source_is_newer() -> None:
    tenant_id = uuid4()
    order_id = uuid4()
    current = OrderAttribution(
        tenant_id=tenant_id,
        order_id=order_id,
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="shop_order_detail",
        source_hash="old-hash",
        source_updated_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    session = FakeSession(order_exists=order_id, current=current, tenant_id=tenant_id)
    incoming_at = datetime(2026, 8, 13, tzinfo=UTC)

    result = asyncio.run(
        OrderAttributionRepository().upsert(
            session, tenant_id, order_id, _decision(incoming_at, marker="new")
        )
    )

    assert result is current
    assert result.source_updated_at == incoming_at
    assert result.evidence_json == {"reason": "new"}
    assert result.source_hash != "old-hash"
    assert session.flushed == 1


@pytest.mark.parametrize(
    "incoming_time,existing_time,marker",
    [
        (datetime(2026, 8, 12, tzinfo=UTC), datetime(2026, 8, 13, tzinfo=UTC), "older"),
        (None, datetime(2026, 8, 13, tzinfo=UTC), "missing-time"),
        (
            datetime(2026, 8, 13, tzinfo=UTC),
            datetime(2026, 8, 13, tzinfo=UTC),
            "conflict",
        ),
    ],
)
def test_upsert_does_not_overwrite_newer_or_same_timestamp_conflicting_signal(
    incoming_time, existing_time, marker
) -> None:
    tenant_id = uuid4()
    order_id = uuid4()
    current = OrderAttribution(
        tenant_id=tenant_id,
        order_id=order_id,
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="shop_order_detail",
        evidence_json={"reason": "current"},
        source_hash="current-hash",
        source_updated_at=existing_time,
    )
    session = FakeSession(order_exists=order_id, current=current, tenant_id=tenant_id)

    result = asyncio.run(
        OrderAttributionRepository().upsert(
            session, tenant_id, order_id, _decision(incoming_time, marker=marker)
        )
    )

    assert result is current
    assert result.evidence_json == {"reason": "current"}
    assert session.flushed == 0


def test_upsert_is_idempotent_for_the_same_decision() -> None:
    tenant_id = uuid4()
    order_id = uuid4()
    decision = _decision(datetime(2026, 8, 13, tzinfo=UTC))
    first_session = FakeSession(order_exists=order_id, tenant_id=tenant_id)
    first = asyncio.run(
        OrderAttributionRepository().upsert(
            first_session, tenant_id, order_id, decision
        )
    )
    second_session = FakeSession(
        order_exists=order_id, current=first, tenant_id=tenant_id
    )

    result = asyncio.run(
        OrderAttributionRepository().upsert(
            second_session, tenant_id, order_id, decision
        )
    )

    assert result is first
    assert second_session.flushed == 0


def test_evidence_merge_accepts_more_evidence_at_the_same_timestamp() -> None:
    tenant_id = uuid4()
    order_id = uuid4()
    source_updated_at = datetime(2026, 8, 13, tzinfo=UTC)
    current = OrderAttribution(
        tenant_id=tenant_id,
        order_id=order_id,
        traffic_source="unknown",
        operator_subject="creator",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="derived",
        classification_method="evidence_merge",
        confidence_score=0.9,
        is_multi_touch=False,
        evidence_summary={"evidence_count": 1, "sources": ["affiliate_order"]},
        source_hash="current-hash",
        source_updated_at=source_updated_at,
    )
    incoming = replace(
        _decision(source_updated_at),
        operator_subject="creator",
        classification_status="derived",
        classification_method="evidence_merge",
        confidence_score=0.9,
        is_multi_touch=True,
        evidence_summary={
            "evidence_count": 2,
            "sources": ["affiliate_order", "seller_order_list"],
        },
    )
    session = FakeSession(order_exists=order_id, current=current, tenant_id=tenant_id)

    result = asyncio.run(
        OrderAttributionRepository().upsert(
            session,
            tenant_id,
            order_id,
            incoming,
        )
    )

    assert result is current
    assert result.is_multi_touch is True
    assert result.evidence_summary == incoming.evidence_summary
    assert session.flushed == 1


def test_source_hash_changes_when_affiliate_ids_change() -> None:
    from erp_api.services.order_attribution_repository import _source_hash

    first = _decision()
    second = replace(first, creator_external_id="creator-1")
    assert _source_hash(first) != _source_hash(second)


def test_upsert_rejects_missing_order_and_mismatched_session_tenant() -> None:
    tenant_id = uuid4()
    order_id = uuid4()
    missing_order_session = FakeSession(order_exists=None, tenant_id=tenant_id)

    with pytest.raises(OrderAttributionOrderNotFound):
        asyncio.run(
            OrderAttributionRepository().upsert(
                missing_order_session, tenant_id, order_id, _decision()
            )
        )

    mismatched_session = FakeSession(order_exists=order_id, tenant_id=uuid4())
    with pytest.raises(TenantContextError):
        asyncio.run(
            OrderAttributionRepository().upsert(
                mismatched_session, tenant_id, order_id, _decision()
            )
        )
