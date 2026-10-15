from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from erp_api.services.sample_auto_assignment_service import (
    PendingSampleAssignment,
    SampleAutoAssignmentService,
)
from erp_api.services.sample_bd_assignment import BdWorkload


class Transaction:
    def __init__(self) -> None:
        self.decision = None

    async def is_assigned(self) -> bool:
        return False

    async def record_decision(self, decision, *, rule_version: str) -> None:
        self.decision = decision


class Repository:
    def __init__(self, request: PendingSampleAssignment) -> None:
        self.request = request
        self.transaction_state = Transaction()

    async def list_pending(self, _tenant_id, _shop_id):
        return (self.request,)

    @asynccontextmanager
    async def transaction(self, _request):
        yield self.transaction_state


class Roster:
    def __init__(self, members) -> None:
        self.members = members

    async def list_members(self, _tenant_id, _shop_id, *, sample_type="free"):
        return self.members


class ReadyImages:
    async def blocked_reason(self, _tenant_id, _shop_id, _application_id):
        return None


class MissingImages:
    async def blocked_reason(self, _tenant_id, _shop_id, _application_id):
        return "sample_image_missing"


@pytest.mark.asyncio
async def test_invalid_roster_fails_closed_and_records_blocked_decision() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    request = PendingSampleAssignment(
        tenant_id=tenant_id,
        shop_id=shop_id,
        application_id=uuid4(),
        creator_level="L3",
        category="测试",
        assignment_key="sample-1",
    )
    members = [
        BdWorkload("BD A", bd_id="bd-a", recipient_open_id="ou-a"),
        BdWorkload("BD B", bd_id="bd-b", recipient_open_id="ou-b"),
    ]
    members[1] = replace(members[1], recipient_open_id="ou-a")
    repository = Repository(request)
    service = SampleAutoAssignmentService(
        repository,
        Roster(members),
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.status == "blocked"
    assert result.blocked_reason == "roster_invalid"
    assert result.blocked_count == 1
    assert repository.transaction_state.decision.blocked_reason == "roster_invalid"


@pytest.mark.asyncio
async def test_missing_sample_image_records_block_without_assigning_bd() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    request = PendingSampleAssignment(
        tenant_id=tenant_id,
        shop_id=shop_id,
        application_id=uuid4(),
        creator_level="L3",
        category="rc-car",
        assignment_key="creator:one",
    )
    repository = Repository(request)
    service = SampleAutoAssignmentService(
        repository,
        Roster([BdWorkload("BD A", bd_id="bd-a", recipient_open_id="ou-a")]),
        MissingImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    result = await service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id)

    assert result.assigned_count == 0
    assert result.blocked_count == 1
    assert result.items[0].blocked_reason == "sample_image_missing"
    assert repository.transaction_state.decision.assigned_bd_name is None
