from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from erp_api.services.sample_cooperation_repository import StoredCooperationAction
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_EXCEPTION_EVENT,
    COOPERATION_OWNER_PROTECTED_EVENT,
    COOPERATION_RECENT_EVENT,
    CooperationCandidate,
    CooperationRecipient,
    CooperationRow,
    CooperationSnapshot,
)
from erp_api.services.sample_cooperation_service import (
    SampleCooperationPrecheckService,
)


class Repository:
    def __init__(self, candidate=None, actions=()) -> None:
        self.candidate = candidate
        self.actions = actions
        self.recorded = ()
        self.completed = []

    async def list_candidates(self, *_args, **_kwargs):
        return (self.candidate,) if self.candidate else ()

    async def record_decisions(self, decisions):
        self.recorded = decisions
        return len(decisions)

    async def list_due_actions(self, *_args, **_kwargs):
        return self.actions

    async def complete_action(self, action, *, message_ids):
        self.completed.append((action.application_id, message_ids))


class Reader:
    async def read(self, **_kwargs):
        return CooperationSnapshot(
            rows=(
                CooperationRow(
                    "童车", "rec-source", "creator-one", "Alice", "2026-09-15"
                ),
            ),
            recipients={"alice": CooperationRecipient("Alice", "ou-alice")},
            valid_creator_ids=frozenset(),
        )

    async def resolve_current_recipient(self, recipient):
        if recipient.name != "Alice":
            return None
        return CooperationRecipient("Alice", "ou-alice")


class RecordClient:
    def __init__(self) -> None:
        self.updates = []

    async def update_business_fields(self, record_id, fields):
        self.updates.append((record_id, fields))


class Router:
    def __init__(self, client) -> None:
        self.client = client

    def for_shop(self, _shop_id):
        return self.client


class Notifications:
    def __init__(self) -> None:
        self.direct = []
        self.group = []

    async def send_text(self, **kwargs):
        self.direct.append(kwargs)
        return "om-direct"

    async def send_text_to_chat(self, **kwargs):
        self.group.append(kwargs)
        return "om-group"


def _candidate() -> CooperationCandidate:
    return CooperationCandidate(
        application_id=uuid4(),
        platform_application_id="application-1",
        creator_id="creator-one",
        shop_name="Akeleo Toys",
        applied_at=datetime(2026, 9, 16, 1, tzinfo=UTC),
    )


def _action(event_type: str, reason: str, *, recipients=()):
    candidate = _candidate()
    return StoredCooperationAction(
        application_id=candidate.application_id,
        shop_id=uuid4(),
        platform_application_id=candidate.platform_application_id,
        creator_id=candidate.creator_id,
        shop_name=candidate.shop_name,
        applied_at=candidate.applied_at,
        feishu_record_id="rec-target",
        event_type=event_type,
        reason=reason,
        matched_count=1,
        recent_date=date(2026, 9, 15),
        sources=("童车",),
        recipients=recipients,
        owner_bd_name=None,
        owner_assigned_at=None,
    )


@pytest.mark.asyncio
async def test_evaluate_records_recent_decision_before_assignment() -> None:
    repository = Repository(candidate=_candidate())
    service = SampleCooperationPrecheckService(
        repository,
        Reader(),
        Notifications(),
        Router(RecordClient()),
        exception_chat_id="oc-exceptions",
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )

    result = await service.evaluate(uuid4(), uuid4(), application_ids=None)

    assert result.evaluated_count == 1
    assert repository.recorded[0].event_type == COOPERATION_RECENT_EVENT


@pytest.mark.asyncio
async def test_recent_action_updates_my_samples_and_sends_plain_text_only() -> None:
    action = _action(
        COOPERATION_RECENT_EVENT,
        "recent_registration",
        recipients=(CooperationRecipient("Alice", "ou-alice"),),
    )
    repository = Repository(actions=(action,))
    records = RecordClient()
    notifications = Notifications()
    service = SampleCooperationPrecheckService(
        repository,
        Reader(),
        notifications,
        Router(records),
        exception_chat_id="oc-exceptions",
    )

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.completed_count == 1
    assert records.updates[0][0] == "rec-target"
    assert "分配BD" not in records.updates[0][1]
    assert records.updates[0][1]["处理结果"] == "近三天已有样品登记，不进入分配记录"
    assert notifications.direct[0]["recipient_open_id"] == "ou-alice"
    assert notifications.group == []
    assert repository.completed == [(action.application_id, ("om-direct",))]


@pytest.mark.asyncio
async def test_active_creator_action_notifies_original_bd_in_plain_text() -> None:
    action = _action(
        COOPERATION_ACTIVE_CREATOR_EVENT,
        "active_creator_after_recent_window",
        recipients=(CooperationRecipient("Alice", "ou-alice"),),
    )
    repository = Repository(actions=(action,))
    records = RecordClient()
    notifications = Notifications()
    service = SampleCooperationPrecheckService(
        repository,
        Reader(),
        notifications,
        Router(records),
        exception_chat_id="oc-exceptions",
    )

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.completed_count == 1
    assert "有效达人" in records.updates[0][1]["处理结果"]
    assert notifications.direct[0]["recipient_open_id"] == "ou-alice"
    assert "有效达人" in notifications.direct[0]["text"]
    assert notifications.group == []


@pytest.mark.asyncio
async def test_assignment_owner_action_notifies_original_bd_only() -> None:
    action = _action(
        COOPERATION_OWNER_PROTECTED_EVENT,
        "creator_assignment_within_7_days",
        recipients=(CooperationRecipient("Alice", "ou-alice"),),
    )
    action = action.__class__(
        **{
            **action.__dict__,
            "owner_bd_name": "Alice",
            "owner_assigned_at": datetime(2026, 9, 22, 1, tzinfo=UTC),
        }
    )
    repository = Repository(actions=(action,))
    records = RecordClient()
    notifications = Notifications()
    service = SampleCooperationPrecheckService(
        repository,
        Reader(),
        notifications,
        Router(records),
        exception_chat_id="oc-exceptions",
    )

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.completed_count == 1
    assert (
        records.updates[0][1]["处理结果"]
        == "本次申请仍由原分配BD跟进，未新增分配记录"
    )
    assert notifications.direct[0]["recipient_open_id"] == "ou-alice"
    assert "原分配BD：Alice" in notifications.direct[0]["text"]
    assert "【新样品申请提醒｜请原BD跟进】" in notifications.direct[0]["text"]
    assert "处理结果：本次申请仍由您跟进，系统未新增分配记录。" in notifications.direct[0]["text"]
    assert "请查看并处理这次新样品申请。" in notifications.direct[0]["text"]


@pytest.mark.asyncio
async def test_exception_action_enters_group_exception_notification() -> None:
    action = _action(COOPERATION_EXCEPTION_EVENT, "bd_recipient_unresolved")
    repository = Repository(actions=(action,))
    notifications = Notifications()
    service = SampleCooperationPrecheckService(
        repository,
        Reader(),
        notifications,
        Router(RecordClient()),
        exception_chat_id="oc-exceptions",
    )

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.completed_count == 1
    assert notifications.direct == []
    assert notifications.group[0]["chat_id"] == "oc-exceptions"
    assert "前置检查异常" in notifications.group[0]["text"]
