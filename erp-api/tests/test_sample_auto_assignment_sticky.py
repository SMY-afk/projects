from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from erp_api.services.sample_auto_assignment_service import (
    PendingSampleAssignment,
    SampleAutoAssignmentService,
)
from erp_api.services.sample_bd_assignment import BdWorkload


class Repository:
    def __init__(self, pending) -> None:
        self.pending = pending
        self.creator_bd = None
        self.creator_bds = {}
        self.compensation_bd = None
        self.decisions = []

    async def list_pending(self, _tenant_id, _shop_id):
        return self.pending

    @asynccontextmanager
    async def transaction(self, request):
        yield Transaction(self, request)


class Transaction:
    def __init__(self, repository, request) -> None:
        self.repository = repository
        self.request = request

    async def is_assigned(self) -> bool:
        return False

    async def load_creator_bd_name(self):
        return self.repository.creator_bds.get(
            self.request.assignment_key, self.repository.creator_bd
        )

    async def load_compensation_bd_name(self):
        return self.repository.compensation_bd

    async def load_workloads(self, roster):
        return roster

    async def record_decision(self, decision, *, rule_version):
        del rule_version
        self.repository.decisions.append(decision)
        if decision.assigned:
            self.repository.creator_bds[self.request.assignment_key] = decision.assigned_bd_name
            if decision.decision_reason == "correction_compensation":
                self.repository.compensation_bd = None


class Roster:
    def __init__(self, members) -> None:
        self.members = members

    async def list_members(self, _tenant_id, _shop_id, *, sample_type="free"):
        return self.members


class ReadyImages:
    async def blocked_reason(self, _tenant_id, _shop_id, _application_id):
        return None


@pytest.mark.asyncio
async def test_same_shop_creator_keeps_first_bd_despite_level_balance():
    tenant_id, shop_id = uuid4(), uuid4()
    pending = [
        PendingSampleAssignment(
            tenant_id=tenant_id,
            shop_id=shop_id,
            application_id=uuid4(),
            creator_level="L3",
            category="rc-car",
            assignment_key="creator:one",
        )
        for _index in range(2)
    ]
    repository = Repository(pending)
    roster = Roster(
        [
            BdWorkload(
                name=f"BD {index}",
                bd_id=f"bd-{index}",
                recipient_open_id=f"ou-{index}",
                categories=frozenset({"rc-car"}),
            )
            for index in range(1, 3)
        ]
    )
    service = SampleAutoAssignmentService(
        repository,
        roster,
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 2
    assert result.blocked_count == 0
    assert repository.decisions[0].assigned_bd_id == "bd-1"
    assert repository.decisions[1].assigned_bd_id == "bd-1"


@pytest.mark.asyncio
async def test_same_creator_affinity_overrides_same_level_rotation():
    tenant_id, shop_id = uuid4(), uuid4()
    request = PendingSampleAssignment(
        tenant_id=tenant_id,
        shop_id=shop_id,
        application_id=uuid4(),
        creator_level="L3",
        category="rc-car",
        assignment_key="creator:one",
    )
    repository = Repository([request])
    repository.creator_bd = "BD 1"
    roster = Roster(
        [
            BdWorkload(
                name="BD 1",
                bd_id="bd-1",
                recipient_open_id="ou-1",
                categories=frozenset({"rc-car"}),
                last_received_levels=frozenset({"L3"}),
            ),
            BdWorkload(
                name="BD 2",
                bd_id="bd-2",
                recipient_open_id="ou-2",
                categories=frozenset({"rc-car"}),
            ),
        ]
    )
    service = SampleAutoAssignmentService(
        repository,
        roster,
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 1
    assert repository.decisions[0].assigned_bd_id == "bd-1"
    assert repository.decisions[0].decision_reason == "same_creator_existing_assignment"


@pytest.mark.asyncio
async def test_same_creator_affinity_overrides_level_imbalance():
    tenant_id, shop_id = uuid4(), uuid4()
    request = PendingSampleAssignment(
        tenant_id=tenant_id,
        shop_id=shop_id,
        application_id=uuid4(),
        creator_level="L2",
        category="rc-car",
        assignment_key="creator:one",
    )
    repository = Repository([request])
    repository.creator_bd = "BD 1"
    roster = Roster(
        [
            BdWorkload(
                name="BD 1",
                bd_id="bd-1",
                recipient_open_id="ou-1",
                categories=frozenset({"rc-car"}),
                total_assigned=8,
                level_counts={"L2": 5},
            ),
            BdWorkload(
                name="BD 2",
                bd_id="bd-2",
                recipient_open_id="ou-2",
                categories=frozenset({"rc-car"}),
                total_assigned=9,
                level_counts={"L2": 2},
            ),
        ]
    )
    service = SampleAutoAssignmentService(
        repository,
        roster,
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 1
    assert result.blocked_count == 0
    assert repository.decisions[0].assigned_bd_id == "bd-1"


@pytest.mark.asyncio
async def test_same_creator_affinity_blocks_instead_of_changing_bd_at_capacity() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    request = PendingSampleAssignment(
        tenant_id=tenant_id,
        shop_id=shop_id,
        application_id=uuid4(),
        creator_level="L2",
        category="rc-car",
        assignment_key="creator:one",
    )
    repository = Repository([request])
    repository.creator_bd = "BD 1"
    roster = Roster(
        [
            BdWorkload(
                name="BD 1",
                bd_id="bd-1",
                recipient_open_id="ou-1",
                categories=frozenset({"rc-car"}),
                current_pending=10,
                capacity=10,
            ),
            BdWorkload(
                name="BD 2",
                bd_id="bd-2",
                recipient_open_id="ou-2",
                categories=frozenset({"rc-car"}),
            ),
        ]
    )
    service = SampleAutoAssignmentService(
        repository,
        roster,
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 0
    assert result.blocked_count == 1
    assert result.items[0].blocked_reason == "same_creator_bd_unavailable"


@pytest.mark.asyncio
async def test_same_creator_affinity_keeps_bd_when_other_bd_is_at_capacity():
    tenant_id, shop_id = uuid4(), uuid4()
    request = PendingSampleAssignment(
        tenant_id=tenant_id,
        shop_id=shop_id,
        application_id=uuid4(),
        creator_level="L2",
        category="rc-car",
        assignment_key="creator:one",
    )
    repository = Repository([request])
    repository.creator_bd = "BD 2"
    roster = Roster(
        [
            BdWorkload(
                name="BD 1",
                bd_id="bd-1",
                recipient_open_id="ou-1",
                categories=frozenset({"rc-car"}),
                current_pending=10,
                capacity=10,
                level_counts={"L2": 1},
            ),
            BdWorkload(
                name="BD 2",
                bd_id="bd-2",
                recipient_open_id="ou-2",
                categories=frozenset({"rc-car"}),
                level_counts={"L2": 2},
            ),
        ]
    )
    service = SampleAutoAssignmentService(
        repository,
        roster,
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 1
    assert result.blocked_count == 0
    assert repository.decisions[0].assigned_bd_id == "bd-2"


@pytest.mark.asyncio
async def test_one_time_compensation_selects_eligible_bd_before_balance():
    tenant_id, shop_id = uuid4(), uuid4()
    requests = [
        PendingSampleAssignment(
            tenant_id=tenant_id,
            shop_id=shop_id,
            application_id=uuid4(),
            creator_level="L3",
            category="rc-car",
            assignment_key=f"username:new-{index}",
        )
        for index in range(2)
    ]
    repository = Repository(requests)
    repository.compensation_bd = "BD 2"
    roster = Roster(
        [
            BdWorkload(
                name="BD 1", bd_id="bd-1", recipient_open_id="ou-1",
                categories=frozenset({"rc-car"}),
            ),
            BdWorkload(
                name="BD 2", bd_id="bd-2", recipient_open_id="ou-2",
                categories=frozenset({"rc-car"}), level_counts={"L3": 3},
            ),
        ]
    )
    service = SampleAutoAssignmentService(
        repository, roster, ReadyImages(), allowed_shop_ids=frozenset({shop_id})
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 2
    assert repository.decisions[0].assigned_bd_id == "bd-2"
    assert repository.decisions[0].decision_reason == "correction_compensation"
    assert repository.decisions[1].assigned_bd_id == "bd-1"
    assert repository.compensation_bd is None
