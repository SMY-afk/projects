from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.feishu_assignment_workload_provider import (
    AssignmentWorkloadDetail,
    FeishuAssignmentWorkloadProvider,
)
from erp_api.services.sample_auto_assignment_service import (
    PendingSampleAssignment,
    SampleAutoAssignmentService,
)
from erp_api.services.sample_bd_assignment import BdWorkload
from tests.test_feishu_assignment_workload_provider import (
    AssignmentClient,
    Details,
    _record,
)
from tests.test_sample_auto_assignment_sticky import (
    ReadyImages,
    Repository,
    Transaction,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_type, expected", [("free", 1), ("refundable", 2)])
async def test_counts_gmv_and_rotation_are_separate(sample_type, expected):
    shop, free, paid1, paid2 = (uuid4() for _ in range(4))
    now = datetime(2026, 10, 12, 8, tzinfo=UTC)
    records = [
        _record(free, bd_name="BD A", assigned_at=now),
        _record(paid1, bd_name="BD B", assigned_at=now),
        _record(paid2, bd_name="BD B", assigned_at=now),
    ]
    details = Details(
        {
            free: AssignmentWorkloadDetail(shop, "L0", 100, "free"),
            paid1: AssignmentWorkloadDetail(shop, "L0", 200, "refundable"),
            paid2: AssignmentWorkloadDetail(shop, "L0", 200, "refundable"),
        }
    )
    provider = FeishuAssignmentWorkloadProvider(AssignmentClient(records), details)
    result = await provider.enrich(
        shop,
        [BdWorkload("BD A"), BdWorkload("BD B")],
        sample_type=sample_type,
    )
    counted, ignored = result if sample_type == "free" else reversed(result)
    assert counted.total_assigned == expected
    assert counted.level_counts == {"L0": expected}
    assert counted.level_gmv_minor_totals == {
        "L0": 100 if sample_type == "free" else 400
    }
    assert counted.last_received_levels == {"L0"}
    assert ignored.total_assigned == 0
    assert ignored.level_counts == {}
    assert ignored.level_gmv_minor_totals == {}
    assert not ignored.last_received_levels


class TypeRoster:
    def __init__(self):
        self.calls = []

    async def list_members(self, tenant_id, shop_id, *, sample_type="free"):
        self.calls.append(sample_type)
        return tuple(
            BdWorkload(name, bd_id=name, recipient_open_id=f"ou-{name}")
            for name in ("BD A", "BD B")
        )


def request(tenant, shop, key, sample_type):
    return PendingSampleAssignment(
        tenant,
        shop,
        uuid4(),
        "L0",
        "*",
        key,
        sample_type=sample_type,
    )


@pytest.mark.asyncio
async def test_mixed_batch_free_priority_and_no_cross_type_delta():
    tenant, shop = uuid4(), uuid4()
    pending = [
        request(tenant, shop, "paid", "refundable"),
        request(tenant, shop, "free", "free"),
    ]
    repo, roster = Repository(pending), TypeRoster()
    service = SampleAutoAssignmentService(
        repo, roster, ReadyImages(), allowed_shop_ids=frozenset({shop})
    )
    result = await service.run_for_shop(tenant_id=tenant, shop_id=shop)
    assert roster.calls == ["free", "refundable"]
    assert [item.application_id for item in result.items] == [
        pending[1].application_id,
        pending[0].application_id,
    ]
    assert [item.decision.assigned_bd_name for item in result.items] == ["BD A", "BD A"]


@pytest.mark.asyncio
async def test_paid_affinity_keeps_original_free_bd():
    tenant, shop = uuid4(), uuid4()
    repo = Repository([request(tenant, shop, "same-creator", "refundable")])
    repo.creator_bd = "BD B"
    service = SampleAutoAssignmentService(
        repo, TypeRoster(), ReadyImages(), allowed_shop_ids=frozenset({shop})
    )
    result = await service.run_for_shop(tenant_id=tenant, shop_id=shop)
    assert result.items[0].decision.assigned_bd_name == "BD B"
    assert (
        result.items[0].decision.decision_reason == "same_creator_existing_assignment"
    )


@pytest.mark.asyncio
async def test_unknown_sample_type_is_fail_closed():
    tenant, shop = uuid4(), uuid4()
    good = request(tenant, shop, "creator", "free")
    repo = Repository([replace(good, sample_type="unknown")])
    service = SampleAutoAssignmentService(
        repo, TypeRoster(), ReadyImages(), allowed_shop_ids=frozenset({shop})
    )
    with pytest.raises(ValueError, match="sample type"):
        await service.run_for_shop(tenant_id=tenant, shop_id=shop)
    assert not repo.decisions


class RecordingRepository(Repository):
    @asynccontextmanager
    async def transaction(self, request):
        parent = self

        class RecordingTransaction(Transaction):
            async def record_decision(self, decision, *, rule_version):
                parent.rule_versions.append(rule_version)
                await super().record_decision(decision, rule_version=rule_version)

        yield RecordingTransaction(self, request)


@pytest.mark.asyncio
async def test_new_paid_assignment_prioritizes_zero_and_persists_v19():
    tenant, shop = uuid4(), uuid4()
    repo = RecordingRepository([request(tenant, shop, "new-paid", "refundable")])
    repo.rule_versions = []

    class PaidRoster(TypeRoster):
        async def list_members(self, tenant_id, shop_id, *, sample_type="free"):
            assert sample_type == "refundable"
            members = await super().list_members(
                tenant_id, shop_id, sample_type=sample_type
            )
            return (
                members[0],
                replace(members[1], level_counts={"L0": 3}, total_assigned=3),
            )

    service = SampleAutoAssignmentService(
        repo, PaidRoster(), ReadyImages(), allowed_shop_ids=frozenset({shop})
    )
    result = await service.run_for_shop(tenant_id=tenant, shop_id=shop)
    assert result.items[0].decision.assigned_bd_name == "BD A"
    assert repo.rule_versions == ["bd-v19-refundable-independent-rotation"]


@pytest.mark.asyncio
async def test_free_assignment_still_persists_v18():
    tenant, shop = uuid4(), uuid4()
    repo = RecordingRepository([request(tenant, shop, "new-free", "free")])
    repo.rule_versions = []
    service = SampleAutoAssignmentService(
        repo, TypeRoster(), ReadyImages(), allowed_shop_ids=frozenset({shop})
    )
    await service.run_for_shop(tenant_id=tenant, shop_id=shop)
    assert repo.rule_versions == ["bd-v18-current-bd-membership-and-image-required"]
