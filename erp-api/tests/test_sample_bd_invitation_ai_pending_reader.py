from dataclasses import replace
from datetime import UTC, datetime

import pytest

from erp_api.services.sample_bd_invitation_protection import (
    BdInvitationProtectionRefresh,
)
from erp_api.services.sample_cooperation_reader import (
    CooperationTableClient,
    SampleCooperationReader,
)


class Rows:
    async def list_record_snapshots(self, **kwargs):
        return ()


class Protection:
    async def refresh(self):
        return replace(
            BdInvitationProtectionRefresh({}, 0, 0),
            pending_creator_ids=frozenset({"erika.withak"}),
        )


class AI:
    async def match_creator_ids(self, *args, **kwargs):
        return frozenset({"erika.withak"})


def reader():
    rows = Rows()
    return SampleCooperationReader(
        (
            CooperationTableClient("source-one", rows, "view-one"),
            CooperationTableClient("source-two", rows, "view-two"),
        ),
        rows,
        rows,
        Protection(),
        ai_invitation_client=AI(),
    )


@pytest.mark.asyncio
async def test_unverified_ai_time_for_current_bd_creator_cannot_reach_autoassignment():
    with pytest.raises(RuntimeError, match="AI invitation time requires verification"):
        await reader().read(creator_ids=frozenset({"@ERIKA.WITHAK"}))


@pytest.mark.asyncio
async def test_unrelated_unverified_ai_time_does_not_block_other_creator():
    from uuid import uuid4

    from erp_api.services.sample_cooperation_rules import (
        COOPERATION_ALLOWED_EVENT,
        CooperationCandidate,
        decide_cooperation,
    )

    snapshot = await reader().read(creator_ids=frozenset({"another.creator"}))
    decision = decide_cooperation(
        CooperationCandidate(uuid4(), "another-application", "another.creator", "test"),
        snapshot,
        today=datetime(2026, 10, 14, tzinfo=UTC).date(),
    )
    assert decision.event_type == COOPERATION_ALLOWED_EVENT
