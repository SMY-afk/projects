import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.sample_notification_avatar import (
    SampleNotificationAvatarError,
)
from erp_api.services.sample_notification_delivery import (
    build_shop_record_url_templates,
)
from erp_api.services.sample_notification_idempotency import (
    notification_delivery_key,
)
from erp_api.services.sample_notification_product_image import (
    SampleNotificationProductImageError,
)
from erp_api.services.sample_notification_service import SampleNotificationService


class FakeRepository:
    def __init__(self, task) -> None:
        self.task = task
        self.succeeded = []
        self.failed = []
        self.message_sent = []
        self.group_message_sent = []

    async def claim(self, *_args, **_kwargs):
        return self.task

    async def succeed(self, *args, **kwargs):
        self.succeeded.append((args, kwargs))

    async def fail(self, *args, **kwargs):
        self.failed.append((args, kwargs))

    async def record_message_sent(self, *args, **kwargs):
        self.message_sent.append((args, kwargs))
        self.task.payload["message_id"] = kwargs["message_id"]
        self.task.payload["message_sent_at"] = kwargs["sent_at"].isoformat()
        return True

    async def record_group_message_sent(self, *args, **kwargs):
        self.group_message_sent.append((args, kwargs))
        self.task.payload["group_message_id"] = kwargs["message_id"]
        self.task.payload["group_message_sent_at"] = kwargs["sent_at"].isoformat()
        return True

    async def list_due(self, **_kwargs):
        return []


class FakeClient:
    def __init__(self, error=None) -> None:
        self.error = error
        self.calls = []

    async def send_card(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return "om-message"

    async def send_card_to_chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return "om-group-message"


class FakeRecordClient:
    def __init__(self, error=None, assigned_bd_name="BD B") -> None:
        self.error = error
        self.assigned_bd_name = assigned_bd_name
        self.calls = []

    async def get_record(self, _record_id):
        return {"分配BD": self.assigned_bd_name}

    async def update_system_fields(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error


@pytest.mark.asyncio
async def test_live_notification_waits_when_sample_record_bd_disagrees() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()
    record_client = FakeRecordClient(assigned_bd_name=None)
    result = await _service(
        repository, client, record_client,
        live_recipients_enabled=True,
        product_image_service=FakeImageService(),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    assert client.calls == []
    assert repository.failed[0][1]["code"] == "sample_assignment_projection_missing"


@pytest.mark.asyncio
async def test_live_notification_waits_when_assignee_id_disagrees() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()
    record_client = FakeRecordClient(
        assigned_bd_name=[{"id": "ou-other", "name": "BD B"}]
    )
    result = await _service(
        repository, client, record_client,
        live_recipients_enabled=True,
        product_image_service=FakeImageService(),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    assert client.calls == []


class FakeImageService:
    def __init__(self, image_key="img_v2_safe", error=None) -> None:
        self.image_key = image_key
        self.error = error
        self.calls = []

    async def resolve_img_key(self, source):
        self.calls.append(source)
        if self.error:
            raise self.error
        return self.image_key


def _task(attempt_count=1):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        recipient_open_id="ou-bd",
        attempt_count=attempt_count,
        payload={
            "feishu_record_id": "rec-1",
            "assigned_bd_name": "BD B",
            "source_event_id": "bd-auto:v7:application-1",
        },
        shop_name="Akeleo Toys",
        creator_name="creator-one",
        creator_username="creator_one",
        creator_level="L4",
        follower_count=741_000,
        creator_gmv_minor=850_000,
        creator_gmv_currency="USD",
        creator_units_sold=167,
        creator_ec_video_view=12_500,
        creator_content_count=28,
        creator_fulfillment_percentage=Decimal("97.35"),
        creator_pps=Decimal("4.0"),
        creator_rating=Decimal("5.0"),
        creator_avatar_object_key="sample/creator-avatars/t/s/c/hash.jpg",
        product_image_urls=(
            "https://p16-oec-general-useast5.ttcdn-us.com/product-1.jpg",
            "https://p16-oec-general-useast5.ttcdn-us.com/product-2.jpg",
        ),
        creator_profile_snapshot=None,
        creator_profile_observed_at=None,
        product_name="Sample product",
        platform_status="PENDING",
        approve_expiration_at=datetime(2026, 9, 10, 4, tzinfo=UTC),
        source_observed_at=datetime(2026, 9, 10, 0, 30, tzinfo=UTC),
        feishu_record_id="rec-1",
    )


def _service(
    repository,
    client,
    record_client=None,
    *,
    test_recipient_open_id="ou-test",
    live_recipients_enabled=False,
    max_attempts=3,
    avatar_service=None,
    product_image_service=None,
    group_chat_id=None,
):
    return SampleNotificationService(
        repository,
        client,
        record_client or FakeRecordClient(),
        record_url_template=(
            "https://example.invalid/configure-resource"
        ),
        test_recipient_open_id=test_recipient_open_id,
        live_recipients_enabled=live_recipients_enabled,
        group_chat_id=group_chat_id,
        max_attempts=max_attempts,
        retry_base_seconds=30,
        processing_timeout=timedelta(minutes=10),
        avatar_service=avatar_service,
        product_image_service=product_image_service,
        clock=lambda: datetime(2026, 9, 10, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_service_sends_and_marks_notification_sent() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()
    avatar_service = FakeImageService()
    product_image_service = FakeImageService("img_v2_product")

    result = await _service(
        repository,
        client,
        avatar_service=avatar_service,
        product_image_service=product_image_service,
    ).deliver(task.tenant_id, task.id)

    assert result.status == "sent"
    assert client.calls[0]["recipient_open_id"] == "ou-test"
    assert client.calls[0]["idempotency_key"] == notification_delivery_key(
        task, channel="direct", target_id="ou-test"
    )
    card = client.calls[0]["card"]
    content = json.dumps(card, ensure_ascii=False)
    assert "TikTok 样品申请 · 待审核" in content
    assert "creator-one" in content
    assert "74.1万" in content
    assert "$8.5K" in content
    assert "97.35%" in content
    assert "Sample product" not in content
    assert "record=rec-1" in content
    assert "测试消息" in content
    assert "img_v2_safe" in content
    assert "img_v2_product" in content
    assert avatar_service.calls == [task.creator_avatar_object_key]
    assert product_image_service.calls == list(task.product_image_urls)
    product_images = [
        child
        for element in card["body"]["elements"]
        for column in element.get("columns", [])
        for child in column.get("elements", [])
        if child.get("tag") == "img" and child.get("preview") is True
    ]
    assert len(product_images) == 2
    assert repository.message_sent
    assert repository.succeeded


@pytest.mark.asyncio
async def test_avatar_failure_degrades_without_blocking_notification() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()
    avatar_service = FakeImageService(
        error=SampleNotificationAvatarError("safe avatar failure")
    )

    result = await _service(
        repository,
        client,
        avatar_service=avatar_service,
    ).deliver(task.tenant_id, task.id)

    assert result.status == "sent"
    assert "img_key" not in json.dumps(client.calls[0]["card"])


@pytest.mark.asyncio
async def test_service_records_message_before_retrying_base_writeback() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()
    record_client = FakeRecordClient(
        FeishuSampleError("private", error_code="http_503")
    )

    first = await _service(repository, client, record_client).deliver(
        task.tenant_id, task.id
    )

    assert first.status == "retry_wait"
    assert len(client.calls) == 1
    assert task.payload["message_id"] == "om-message"

    record_client.error = None
    second = await _service(repository, client, record_client).deliver(
        task.tenant_id, task.id
    )

    assert second.status == "sent"
    assert len(client.calls) == 1
    assert record_client.calls[-1] == (
        (
            "rec-1",
            {"通知状态": "已通知", "通知时间": 1789002000000},
        ),
        {},
    )


@pytest.mark.asyncio
async def test_service_routes_writeback_and_card_link_to_task_shop() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()
    default_record_client = FakeRecordClient()
    shop_record_client = FakeRecordClient()

    class Router:
        def for_shop(self, shop_id):
            assert shop_id == task.shop_id
            return shop_record_client

    service = SampleNotificationService(
        repository,
        client,
        Router(),
        record_url_template=(
            "https://example.invalid/configure-resource"
            "?table=default-table&record={record_id}"
        ),
        record_url_templates_by_shop=build_shop_record_url_templates(
            "https://example.invalid/configure-resource"
            "?table=default-table&view=wrong-view&record={record_id}",
            {task.shop_id: "shop-table"},
        ),
        test_recipient_open_id="ou-test",
        live_recipients_enabled=False,
        max_attempts=3,
        retry_base_seconds=30,
        processing_timeout=timedelta(minutes=10),
        clock=lambda: datetime(2026, 9, 10, 1, tzinfo=UTC),
    )

    result = await service.deliver(task.tenant_id, task.id)

    assert result.status == "sent"
    card = json.dumps(client.calls[0]["card"], ensure_ascii=False)
    assert "table=shop-table" in card
    assert "record=rec-1" in card
    assert "wrong-view" not in card
    assert shop_record_client.calls
    assert default_record_client.calls == []


@pytest.mark.asyncio
async def test_service_persists_retryable_failure_without_upstream_message() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient(
        FeishuSampleError(
            "sensitive upstream response",
            error_code="http_503",
            request_id="request-id",
        )
    )

    result = await _service(repository, client).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    failure = repository.failed[0][1]
    assert failure["code"] == "http_503"
    assert failure["retry_at"] == datetime(2026, 9, 10, 1, 0, 30, tzinfo=UTC)
    assert "sensitive" not in failure["summary"]


@pytest.mark.asyncio
async def test_service_only_uses_live_bd_after_explicit_enablement() -> None:
    task = _task()
    task.creator_profile_snapshot = {
        "schema_version": 2,
        "creator_details_complete": True,
    }
    task.creator_profile_observed_at = datetime(2026, 9, 10, 1, tzinfo=UTC)
    repository = FakeRepository(task)
    client = FakeClient()

    result = await _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        group_chat_id="oc-business",
        product_image_service=FakeImageService("img_v2_product"),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "sent"
    assert client.calls[0]["recipient_open_id"] == "ou-bd"
    assert client.calls[1]["chat_id"] == "oc-business"
    assert client.calls[1]["idempotency_key"] == notification_delivery_key(
        task, channel="group", target_id="oc-business"
    )
    assert repository.group_message_sent
    assert "测试消息" not in json.dumps(client.calls[0]["card"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_service_retries_only_missing_group_delivery() -> None:
    task = _task()
    task.creator_profile_snapshot = {
        "schema_version": 2,
        "creator_details_complete": True,
    }
    task.creator_profile_observed_at = datetime(2026, 9, 10, 1, tzinfo=UTC)
    repository = FakeRepository(task)

    class PartialFailureClient(FakeClient):
        async def send_card_to_chat(self, **kwargs):
            self.calls.append(kwargs)
            if len([call for call in self.calls if "chat_id" in call]) == 1:
                raise FeishuSampleError("private", error_code="http_503")
            return "om-group-message"

    client = PartialFailureClient()
    service = _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        group_chat_id="oc-business",
        product_image_service=FakeImageService("img_v2_product"),
    )

    first = await service.deliver(task.tenant_id, task.id)
    second = await service.deliver(task.tenant_id, task.id)

    assert first.status == "retry_wait"
    assert second.status == "sent"
    assert len([call for call in client.calls if "recipient_open_id" in call]) == 1
    assert len([call for call in client.calls if "chat_id" in call]) == 2


@pytest.mark.asyncio
async def test_live_notification_retries_when_product_images_are_unavailable() -> None:
    task = _task()
    task.creator_profile_snapshot = {
        "schema_version": 2,
        "creator_details_complete": True,
    }
    task.creator_profile_observed_at = datetime(2026, 9, 10, 1, tzinfo=UTC)
    repository = FakeRepository(task)
    client = FakeClient()
    product_image_service = FakeImageService(
        error=SampleNotificationProductImageError("safe image failure")
    )

    result = await _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        group_chat_id="oc-business",
        product_image_service=product_image_service,
    ).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    assert client.calls == []
    assert repository.failed[0][1]["code"] == "product_image_unavailable"
    assert repository.failed[0][1]["retry_at"] == datetime(
        2026, 9, 10, 1, 0, 30, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_live_notification_retries_when_product_image_url_is_missing() -> None:
    task = _task()
    task.product_image_urls = ()
    repository = FakeRepository(task)
    client = FakeClient()

    result = await _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        group_chat_id="oc-business",
        product_image_service=FakeImageService("img_v2_product"),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    assert client.calls == []
    assert repository.failed[0][1]["code"] == "product_image_unavailable"


@pytest.mark.asyncio
async def test_live_notification_waits_for_creator_level_before_sending() -> None:
    task = _task()
    task.creator_level = None
    task.creator_gmv_minor = None
    repository = FakeRepository(task)
    client = FakeClient()

    result = await _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        group_chat_id="oc-business",
        product_image_service=FakeImageService("img_v2_product"),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    assert client.calls == []
    assert repository.failed[0][1]["code"] == "creator_profile_incomplete"
    assert repository.failed[0][1]["retry_at"] == datetime(
        2026, 9, 10, 1, 0, 30, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_live_notification_sends_without_creator_details() -> None:
    task = _task()
    repository = FakeRepository(task)
    client = FakeClient()

    result = await _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        product_image_service=FakeImageService("img_v2_product"),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "sent"
    assert len(client.calls) == 1
    assert repository.failed == []


@pytest.mark.asyncio
async def test_live_notification_sends_with_stale_creator_details() -> None:
    task = _task()
    task.creator_profile_snapshot = {
        "schema_version": 2,
        "creator_details_complete": True,
    }
    task.creator_profile_observed_at = datetime(2026, 9, 10, 0, 54, tzinfo=UTC)
    repository = FakeRepository(task)
    client = FakeClient()

    result = await _service(
        repository,
        client,
        test_recipient_open_id=None,
        live_recipients_enabled=True,
        product_image_service=FakeImageService("img_v2_product"),
    ).deliver(task.tenant_id, task.id)

    assert result.status == "sent"
    assert len(client.calls) == 1
    assert repository.failed == []


@pytest.mark.asyncio
async def test_retryable_notification_failure_is_retried_only_once() -> None:
    first = _task(attempt_count=1)
    first_repository = FakeRepository(first)
    first_result = await _service(
        first_repository,
        FakeClient(FeishuSampleError("private", error_code="http_503")),
        max_attempts=2,
    ).deliver(first.tenant_id, first.id)

    second = _task(attempt_count=2)
    second_repository = FakeRepository(second)
    second_result = await _service(
        second_repository,
        FakeClient(FeishuSampleError("private", error_code="http_503")),
        max_attempts=2,
    ).deliver(second.tenant_id, second.id)

    assert first_result.status == "retry_wait"
    assert second_result.status == "failed"
    assert second_repository.failed[0][1]["retry_at"] is None


@pytest.mark.asyncio
async def test_bitable_internal_failure_is_retried_without_resending_evidence() -> None:
    task = _task(attempt_count=1)
    sent_at = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    task.payload.update(
        {
            "message_id": "om-direct",
            "message_sent_at": sent_at.isoformat(),
            "group_message_id": "om-group",
            "group_message_sent_at": sent_at.isoformat(),
        }
    )
    repository = FakeRepository(task)
    client = FakeClient()
    record_client = FakeRecordClient(
        error=FeishuSampleError("private", error_code="1254002")
    )

    result = await _service(
        repository,
        client,
        record_client=record_client,
        max_attempts=2,
    ).deliver(task.tenant_id, task.id)

    assert result.status == "retry_wait"
    assert result.retry_after_seconds == 30
    assert client.calls == []
    assert repository.failed[0][1]["code"] == "1254002"
    assert repository.failed[0][1]["retry_at"] is not None


def test_duplicate_outboxes_share_delivery_idempotency_key() -> None:
    first = _task()
    duplicate = _task()

    assert first.id != duplicate.id
    assert notification_delivery_key(
        first, channel="direct", target_id=first.recipient_open_id
    ) == notification_delivery_key(
        duplicate, channel="direct", target_id=duplicate.recipient_open_id
    )


@pytest.mark.asyncio
async def test_service_sanitizes_error_code_and_applies_exponential_backoff() -> None:
    for attempt_count, expected_delay in [(1, 30), (2, 60), (3, 120)]:
        task = _task(attempt_count)
        repository = FakeRepository(task)

        result = await _service(
            repository,
            FakeClient(FeishuSampleError("private", error_code="http_503")),
            max_attempts=5,
        ).deliver(task.tenant_id, task.id)

        assert result.retry_after_seconds == expected_delay
        stored = repository.failed[0][1]
        assert stored["code"] == "http_503"

    task = _task()
    repository = FakeRepository(task)
    await _service(
        repository,
        FakeClient(FeishuSampleError("private", error_code="token=private")),
    ).deliver(task.tenant_id, task.id)
    assert repository.failed[0][1]["code"] == "feishu_error"


@pytest.mark.asyncio
async def test_service_stops_retrying_permanent_or_exhausted_failures() -> None:
    for error, attempt_count in [
        (FeishuSampleError("private", error_code="230001"), 1),
        (FeishuSampleError("private", error_code="http_503"), 3),
    ]:
        task = _task(attempt_count)
        repository = FakeRepository(task)

        result = await _service(repository, FakeClient(error)).deliver(
            task.tenant_id, task.id
        )

        assert result.status == "failed"
        assert repository.failed[0][1]["retry_at"] is None
