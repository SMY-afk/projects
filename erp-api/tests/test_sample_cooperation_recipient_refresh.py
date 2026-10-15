from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.sample_cooperation_records import StoredCooperationAction
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_OWNER_PROTECTED_EVENT,
    CooperationRecipient,
)
from erp_api.services.sample_cooperation_service import (
    SampleCooperationPrecheckService,
)


class Repository:
    def __init__(self, action):
        self.action = action
        self.completed = []

    async def list_due_actions(self, *_args):
        return (self.action,)

    async def complete_action(self, action, *, message_ids):
        self.completed.append((action.application_id, message_ids))


class Reader:
    async def resolve_current_recipient(self, recipient):
        if recipient.name == "Alice":
            return CooperationRecipient("Alice", "ou-current-app")
        return None


class Records:
    def __init__(self):
        self.updates = []

    async def update_business_fields(self, record_id, fields):
        self.updates.append((record_id, fields))


class Notifications:
    def __init__(self, *, reject=False):
        self.direct = []
        self.reject = reject

    async def send_text(self, **kwargs):
        if self.reject:
            raise FeishuSampleError("Rejected", error_code="230001")
        self.direct.append(kwargs)
        return "om-direct"


def _action(*, owner="Alice", old_open_id="ou-old-app"):
    return StoredCooperationAction(
        application_id=uuid4(),
        shop_id=uuid4(),
        platform_application_id="application-1",
        creator_id="creator-one",
        shop_name="Shop",
        applied_at=datetime(2026, 10, 7, tzinfo=UTC),
        feishu_record_id="rec-target",
        event_type=COOPERATION_OWNER_PROTECTED_EVENT,
        reason="creator_assignment_within_7_days",
        matched_count=1,
        recent_date=None,
        sources=(),
        recipients=(CooperationRecipient("Alice", old_open_id),),
        owner_bd_name=owner,
        owner_assigned_at=datetime(2026, 10, 6, tzinfo=UTC),
    )


def _service(action, *, reject=False):
    repository = Repository(action)
    records = Records()
    notifications = Notifications(reject=reject)
    service = SampleCooperationPrecheckService(
        repository,
        Reader(),
        notifications,
        records,
        exception_chat_id="oc-exceptions",
    )
    return service, repository, records, notifications


@pytest.mark.asyncio
async def test_owner_notice_refreshes_stale_app_open_id_from_exact_roster():
    action = _action()
    service, repository, _records, notifications = _service(action)

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.completed_count == 1
    assert notifications.direct[0]["recipient_open_id"] == "ou-current-app"
    assert repository.completed == [(action.application_id, ("om-direct",))]


@pytest.mark.asyncio
async def test_owner_notice_rejects_mismatched_owner_and_recipient():
    action = _action(owner="Bob")
    service, repository, records, notifications = _service(action)

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.failed_count == 1
    assert records.updates == []
    assert notifications.direct == []
    assert repository.completed == []


@pytest.mark.asyncio
async def test_rejected_notice_logs_safe_error_code(caplog):
    action = _action(old_open_id="ou-current-app")
    service, repository, _records, _notifications = _service(action, reject=True)

    result = await service.complete_due(uuid4(), action.shop_id)

    assert result.failed_count == 1
    assert repository.completed == []
    failure = next(
        record for record in caplog.records
        if record.message == "sample_cooperation_action_failed"
    )
    assert failure.error_code == "230001"
