from datetime import UTC, date, datetime
from uuid import uuid4

from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ALLOWED_EVENT,
    CooperationCandidate,
    CooperationSnapshot,
    decide_cooperation,
)


def test_ai_invitation_hit_alone_allows_automatic_assignment() -> None:
    candidate = CooperationCandidate(
        application_id=uuid4(),
        platform_application_id="application-1",
        creator_id="creator-one",
        shop_name="Akeleo Toys",
    )
    snapshot = CooperationSnapshot(
        rows=(),
        recipients={},
        ai_invitation_creator_ids=frozenset({"creator-one"}),
    )

    decision = decide_cooperation(
        candidate,
        snapshot,
        today=date(2026, 9, 23),
        now=datetime(2026, 9, 23, 8, tzinfo=UTC),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "not_registered"
    assert not decision.blocks_assignment
