from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_notification_repository import (
    SampleNotificationRepository,
)


class FakeSession:
    def __init__(self, event, workflow, context=None) -> None:
        self.event = event
        self.workflow = workflow
        if not hasattr(self.workflow, "assigned_bd_name"):
            self.workflow.assigned_bd_name = event.payload.get("assigned_bd_name")
        self.context = context or (
            "Akeleo Toys",
            "creator-one",
            "creator_user",
            "creator-open-id",
            "L4",
            741_000,
            850_000,
            "USD",
            167,
            12_500,
            28,
            Decimal("97.35"),
            Decimal("4.0"),
            Decimal("5.0"),
            "sample/creator-avatars/t/s/c/hash.jpg",
            {"schema_version": 2},
            datetime(2026, 9, 10, tzinfo=UTC),
            "Sample product",
            "Sample SKU",
            "product-1",
            "https://p16-oec-general-useast5.ttcdn-us.com/product.jpg",
            [],
            "PENDING",
            datetime(2026, 9, 11, tzinfo=UTC),
            datetime(2026, 9, 10, tzinfo=UTC),
            {"is_proactive_invitation": False},
            True,
            True,
        )
        self.commits = 0
        self.execute_count = 0
        self.product_rows = (
            ("https://p16-oec-general-useast5.ttcdn-us.com/product.jpg",),
            ("https://p16-oec-general-useast5.ttcdn-us.com/product-2.jpg",),
            ("https://p16-oec-general-useast5.ttcdn-us.com/product.jpg",),
        )
        self.scalar_calls = 0
        self.latest_event_id = event.id

    async def get(self, model, event_id, *, with_for_update=False):
        assert model is SampleNotificationOutbox
        assert event_id == self.event.id
        assert with_for_update is True
        return self.event

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.workflow if self.scalar_calls == 1 else self.latest_event_id

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return SimpleNamespace(one_or_none=lambda: self.context)
        return SimpleNamespace(all=lambda: self.product_rows)

    async def commit(self):
        self.commits += 1


class FakeDatabase:
    def __init__(self, session) -> None:
        self.fake_session = session

    async def session(self, _tenant_id):
        yield self.fake_session


def _event(**overrides):
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "shop_id": uuid4(),
        "sample_application_id": uuid4(),
        "assignment_version": 2,
        "recipient_open_id": "ou-bd",
        "payload": {"feishu_record_id": "rec-1", "assigned_bd_name": "BD B"},
        "status": "pending",
        "attempt_count": 0,
        "next_attempt_at": None,
        "sent_at": None,
        "last_error_code": None,
        "last_error_summary": None,
        "updated_at": datetime(2026, 9, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_claim_checks_current_assignment_and_marks_processing() -> None:
    event = _event()
    session = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is not None
    assert task.shop_id == event.shop_id
    assert task.recipient_open_id == "ou-bd"
    assert task.attempt_count == 1
    assert task.shop_name == "Akeleo Toys"
    assert task.creator_name == "creator-one"
    assert task.creator_level == "L4"
    assert task.follower_count == 741_000
    assert task.creator_gmv_minor == 850_000
    assert task.creator_avatar_object_key.endswith("hash.jpg")
    assert task.creator_profile_snapshot == {"schema_version": 2}
    assert task.product_name == "Sample product"
    assert task.product_image_urls == (
        "https://p16-oec-general-useast5.ttcdn-us.com/product.jpg",
        "https://p16-oec-general-useast5.ttcdn-us.com/product-2.jpg",
    )
    assert task.feishu_record_id == "rec-1"
    assert event.status == "processing"
    assert event.attempt_count == 1
    assert session.commits == 1


@pytest.mark.asyncio
async def test_claim_cancels_task_for_old_assignment_version() -> None:
    event = _event()
    session = FakeSession(
        event, SimpleNamespace(assignment_version=3, feishu_record_id="rec-1")
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is None
    assert event.status == "cancelled"
    assert session.commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_payload",
    [
        {},
    ],
)
async def test_claim_cancels_when_application_source_is_not_verified(raw_payload) -> None:
    event = _event()
    default_context = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    ).context
    context = (*default_context[:-3], raw_payload, True, True)
    session = FakeSession(
        event,
        SimpleNamespace(assignment_version=2, feishu_record_id="rec-1"),
        context=context,
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is None
    assert event.status == "cancelled"
    assert event.next_attempt_at is None
    assert event.last_error_code == "unverified_application_source"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_claim_accepts_verified_target_collaboration_application() -> None:
    event = _event()
    default_context = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    ).context
    context = (
        *default_context[:-3],
        {"is_proactive_invitation": True},
        True,
        True,
    )
    session = FakeSession(
        event,
        SimpleNamespace(assignment_version=2, feishu_record_id="rec-1"),
        context=context,
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is not None
    assert event.status == "processing"


@pytest.mark.asyncio
async def test_claim_cancels_superseded_group_projection() -> None:
    event = _event()
    default_context = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    ).context
    context = (*default_context[:-2], False, True)
    session = FakeSession(
        event,
        SimpleNamespace(assignment_version=2, feishu_record_id="rec-1"),
        context=context,
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is None
    assert event.status == "cancelled"
    assert event.last_error_code == "superseded_application_projection"


@pytest.mark.asyncio
async def test_claim_cancels_non_approvable_current_application() -> None:
    event = _event()
    default_context = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    ).context
    context = (*default_context[:-1], False)
    session = FakeSession(
        event,
        SimpleNamespace(assignment_version=2, feishu_record_id="rec-1"),
        context=context,
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id, event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is None
    assert event.status == "cancelled"
    assert event.last_error_code == "non_approvable_application"


@pytest.mark.asyncio
async def test_claim_blocks_notice_when_local_bd_was_cleared() -> None:
    event = _event()
    session = FakeSession(
        event,
        SimpleNamespace(
            assignment_version=2, feishu_record_id="rec-1", assigned_bd_name=None
        ),
    )
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id, event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is None
    assert event.status == "failed"
    assert event.last_error_code == "assignment_owner_mismatch"


@pytest.mark.asyncio
async def test_claim_keeps_only_latest_notification_for_creator_and_shop() -> None:
    event = _event()
    session = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    )
    session.latest_event_id = uuid4()
    repository = SampleNotificationRepository(FakeDatabase(session))

    task = await repository.claim(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    assert task is None
    assert event.status == "cancelled"
    assert event.last_error_code == "duplicate_creator_shop_notification"


@pytest.mark.asyncio
async def test_sent_and_failed_transitions_only_update_processing_task() -> None:
    event = _event(status="processing", attempt_count=1)
    session = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    )
    repository = SampleNotificationRepository(FakeDatabase(session))
    now = datetime(2026, 9, 10, 1, tzinfo=UTC)

    await repository.fail(
        event.tenant_id,
        event.id,
        code="http_503",
        summary="Feishu notification request failed.",
        retry_at=now + timedelta(seconds=30),
    )
    assert event.status == "retry_wait"
    assert event.last_error_code == "http_503"

    event.status = "processing"
    await repository.succeed(event.tenant_id, event.id, sent_at=now)
    assert event.status == "sent"
    assert event.sent_at == now
    assert event.last_error_code is None


@pytest.mark.asyncio
async def test_message_delivery_evidence_is_saved_before_base_writeback() -> None:
    event = _event(status="processing", attempt_count=1)
    session = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    )
    repository = SampleNotificationRepository(FakeDatabase(session))
    now = datetime(2026, 9, 10, 1, tzinfo=UTC)

    persisted = await repository.record_message_sent(
        event.tenant_id,
        event.id,
        message_id="om-message",
        sent_at=now,
    )

    assert persisted is True
    assert event.payload["message_id"] == "om-message"
    assert event.payload["message_sent_at"] == now.isoformat()

    persisted = await repository.record_group_message_sent(
        event.tenant_id,
        event.id,
        message_id="om-group-message",
        sent_at=now,
    )

    assert persisted is True
    assert event.payload["group_message_id"] == "om-group-message"
    assert event.payload["group_message_sent_at"] == now.isoformat()


@pytest.mark.asyncio
async def test_operator_can_requeue_unavailable_recipient_without_message_evidence():
    event = _event(
        status="failed",
        attempt_count=1,
        last_error_code="230013",
        last_error_summary="Feishu notification request failed.",
    )
    session = FakeSession(
        event, SimpleNamespace(assignment_version=2, feishu_record_id="rec-1")
    )
    repository = SampleNotificationRepository(FakeDatabase(session))
    now = datetime(2026, 9, 10, 2, tzinfo=UTC)

    requeued = await repository.requeue_unavailable_recipient(
        event.tenant_id, event.id, now=now
    )

    assert requeued is True
    assert event.status == "pending"
    assert event.attempt_count == 0
    assert event.next_attempt_at == now
    assert event.last_error_code is None


@pytest.mark.asyncio
async def test_operator_retry_rejects_event_with_delivery_evidence() -> None:
    event = _event(
        status="failed",
        attempt_count=1,
        last_error_code="230013",
        payload={"message_id": "om-existing"},
    )
    repository = SampleNotificationRepository(
        FakeDatabase(FakeSession(event, SimpleNamespace()))
    )

    requeued = await repository.requeue_unavailable_recipient(
        event.tenant_id,
        event.id,
        now=datetime(2026, 9, 10, 2, tzinfo=UTC),
    )

    assert requeued is False


@pytest.mark.asyncio
async def test_daily_reconciliation_requeues_only_current_failed_assignments() -> None:
    class Result:
        def all(self):
            return [(uuid4(),), (uuid4(),)]

    class Session:
        def __init__(self) -> None:
            self.statements = []
            self.commits = 0

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

        async def commit(self):
            self.commits += 1

    class Database:
        def __init__(self) -> None:
            self.session = Session()

        @asynccontextmanager
        async def system_session_factory(self):
            yield self.session

    database = Database()
    repository = SampleNotificationRepository(database)

    count = await repository.requeue_current_failures(
        now=datetime(2026, 9, 17, tzinfo=UTC)
    )

    assert count == 2
    assert database.session.commits == 1
    sql = str(database.session.statements[0])
    assert "sample_notification_outbox.status =" in sql
    assert "sample_notification_outbox.assignment_version = " in sql
    assert "sample_application_workflows.assignment_version" in sql
    assert "sample_application_workflows.assigned_bd_name IS NOT NULL" in sql
    assert "sample_applications.is_current_projection IS true" in sql
