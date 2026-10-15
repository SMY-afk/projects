from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.sample_application_mapper import (
    ACTIVE_SAMPLE_STATUSES,
    TERMINAL_SAMPLE_STATUSES,
)
from erp_api.workers import sample_application_jobs as jobs


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


def test_active_dispatcher_enqueues_one_shop_scoped_job_for_all_statuses(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    async def authorized(database):
        return [(tenant_id, shop_id)]

    monkeypatch.setattr(jobs, "_authorized_sample_shops", authorized)
    redis = FakeRedis()
    count = asyncio.run(
        jobs.enqueue_active_sample_application_polls(
            {
                "database": object(),
                "redis": redis,
                "now": datetime(2026, 9, 9, 1, 12, tzinfo=UTC),
            }
        )
    )

    assert count == 1
    args, kwargs = redis.calls[0]
    assert args[1:4] == (str(tenant_id), str(shop_id), "active")
    assert set(args[4]) == ACTIVE_SAMPLE_STATUSES
    assert args[5:] == ("official_api", False)
    assert kwargs["_job_id"].endswith("active:202609090102")


def test_terminal_dispatcher_uses_only_official_api_statuses(monkeypatch) -> None:
    tenant_id, shop_id = uuid4(), uuid4()

    async def authorized(database):
        return [(tenant_id, shop_id)]

    monkeypatch.setattr(jobs, "_authorized_sample_shops", authorized)
    redis = FakeRedis()
    count = asyncio.run(
        jobs.enqueue_terminal_sample_application_polls(
            {
                "database": object(),
                "redis": redis,
                "now": datetime(2026, 9, 9, 1, 12, tzinfo=UTC),
            }
        )
    )

    assert count == 1
    args, _kwargs = redis.calls[0]
    assert set(args[4]) == TERMINAL_SAMPLE_STATUSES
    assert "CANCELLED" not in args[4]


def test_active_dispatcher_does_not_scan_feishu_before_enqueue(
    monkeypatch,
) -> None:
    events = []

    class ReversePoll:
        async def poll(self):
            events.append("reverse_poll")

    async def authorized(database):
        events.append("list_shops")
        return []

    monkeypatch.setattr(jobs, "_authorized_sample_shops", authorized)

    count = asyncio.run(
        jobs.enqueue_active_sample_application_polls(
            {
                "database": object(),
                "redis": FakeRedis(),
                "feishu_sample_reverse_poll_service": ReversePoll(),
            }
        )
    )

    assert count == 0
    assert events == ["list_shops"]


def test_full_reconciliation_uses_daily_idempotency_bucket(monkeypatch) -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    async def authorized(database):
        return [(tenant_id, shop_id)]

    monkeypatch.setattr(jobs, "_authorized_sample_shops", authorized)
    redis = FakeRedis()
    count = asyncio.run(
        jobs.enqueue_sample_application_reconciliation(
            {
                "database": object(),
                "redis": redis,
                "now": datetime(2026, 9, 9, 19, 30, tzinfo=UTC),
            }
        )
    )

    assert count == 1
    args, kwargs = redis.calls[0]
    assert args == (
        "reconcile_sample_applications_job",
        str(tenant_id),
        str(shop_id),
        "official_api",
        False,
    )
    assert kwargs["_job_id"].endswith("full:20260909")


def test_sync_job_holds_one_shop_lock_for_all_statuses() -> None:
    tenant_id, shop_id = uuid4(), uuid4()

    class Service:
        def __init__(self) -> None:
            self.calls = []

        async def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return tuple(kwargs["statuses"])

    class Lock:
        @asynccontextmanager
        async def acquire(self, actual_tenant_id, actual_shop_id):
            assert (actual_tenant_id, actual_shop_id) == (tenant_id, shop_id)
            yield True

    service = Service()
    result = asyncio.run(
        jobs.sync_sample_applications_job(
            {
                "sample_shop_pipeline_service": service,
                "sample_shop_sync_lock": Lock(),
            },
            str(tenant_id),
            str(shop_id),
            "active",
            ["PENDING", "SHIPPED"],
        )
    )

    assert result == ("PENDING", "SHIPPED")
    assert service.calls[0][1] == {
        "mode": "active",
        "statuses": ["PENDING", "SHIPPED"],
        "source_type": "official_api",
        "dry_run": False,
    }


def test_reconciliation_job_uses_full_mode_and_explicit_source() -> None:
    tenant_id, shop_id = uuid4(), uuid4()

    class Pipeline:
        async def run(self, *args, **kwargs):
            return args, kwargs

    class Lock:
        @asynccontextmanager
        async def acquire(self, *_args):
            yield True

    args, kwargs = asyncio.run(
        jobs.reconcile_sample_applications_job(
            {
                "sample_shop_pipeline_service": Pipeline(),
                "sample_shop_sync_lock": Lock(),
            },
            str(tenant_id),
            str(shop_id),
            "official_api",
            True,
        )
    )

    assert args == (tenant_id, shop_id)
    assert kwargs == {
        "mode": "full",
        "statuses": [None],
        "source_type": "official_api",
        "dry_run": True,
    }


def test_sync_job_retries_when_same_shop_is_locked() -> None:
    from arq import Retry

    class Lock:
        @asynccontextmanager
        async def acquire(self, *_args):
            yield False

    with pytest.raises(Retry) as raised:
        asyncio.run(
            jobs.sync_sample_applications_job(
                {
                    "sample_shop_pipeline_service": object(),
                    "sample_shop_sync_lock": Lock(),
                    "sample_shop_lock_retry_seconds": 45,
                },
                str(uuid4()),
                str(uuid4()),
                "active",
                ["PENDING"],
            )
        )

    assert raised.value.defer_score == 45_000


def test_source_recovery_dispatcher_enqueues_only_repository_candidates() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    class Recovery:
        async def candidates(self):
            return [(tenant_id, shop_id)]

    redis = FakeRedis()
    count = asyncio.run(
        jobs.enqueue_sample_source_recoveries(
            {
                "sample_source_recovery_service": Recovery(),
                "redis": redis,
                "now": datetime(2026, 9, 10, 1, 12, tzinfo=UTC),
            }
        )
    )

    assert count == 1
    args, kwargs = redis.calls[0]
    assert args == (
        "recover_sample_application_source_job",
        str(tenant_id),
        str(shop_id),
    )
    assert kwargs["_job_id"].endswith("202609100102")


def test_source_recovery_job_uses_the_same_shop_lock() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    events = []

    class Recovery:
        async def recover(self, actual_tenant_id, actual_shop_id):
            events.append(("recover", actual_tenant_id, actual_shop_id))
            return "recovered"

    class Lock:
        @asynccontextmanager
        async def acquire(self, actual_tenant_id, actual_shop_id):
            events.append(("lock", actual_tenant_id, actual_shop_id))
            yield True

    result = asyncio.run(
        jobs.recover_sample_application_source_job(
            {
                "sample_source_recovery_service": Recovery(),
                "sample_shop_sync_lock": Lock(),
            },
            str(tenant_id),
            str(shop_id),
        )
    )

    assert result == "recovered"
    assert events == [
        ("lock", tenant_id, shop_id),
        ("recover", tenant_id, shop_id),
    ]


def test_reverse_poll_dispatcher_is_disabled_without_service() -> None:
    count = asyncio.run(
        jobs.enqueue_feishu_sample_reverse_poll(
            {"redis": FakeRedis(), "now": datetime(2026, 9, 10, 1, 12, tzinfo=UTC)}
        )
    )

    assert count == 0


def test_reverse_poll_dispatcher_enqueues_single_idempotent_job() -> None:
    redis = FakeRedis()
    count = asyncio.run(
        jobs.enqueue_feishu_sample_reverse_poll(
            {
                "feishu_sample_reverse_poll_service": object(),
                "redis": redis,
                "now": datetime(2026, 9, 10, 1, 12, tzinfo=UTC),
            }
        )
    )

    assert count == 1
    args, kwargs = redis.calls[0]
    assert args == ("poll_feishu_sample_business_fields_job", False)
    assert kwargs["_job_id"].endswith("202609100112")


def test_reverse_poll_daily_audit_enqueues_full_scan() -> None:
    redis = FakeRedis()
    count = asyncio.run(
        jobs.enqueue_feishu_sample_reverse_poll_audit(
            {
                "feishu_sample_reverse_poll_service": object(),
                "redis": redis,
                "now": datetime(2026, 9, 10, 18, 30, tzinfo=UTC),
            }
        )
    )

    assert count == 1
    args, kwargs = redis.calls[0]
    assert args == ("poll_feishu_sample_business_fields_job", True)
    assert kwargs["_job_id"] == "feishu-sample-reverse-poll-audit:20260910"


def test_reverse_poll_has_separate_low_frequency_cron() -> None:
    from erp_api.workers.sample_settings import SampleWorkerSettings

    assert jobs.poll_feishu_sample_business_fields_job in SampleWorkerSettings.functions
    scheduled = next(
        job
        for job in SampleWorkerSettings.cron_jobs
        if job.coroutine is jobs.enqueue_feishu_sample_reverse_poll
    )
    assert scheduled.minute == {0}
    audit = next(
        job
        for job in SampleWorkerSettings.cron_jobs
        if job.coroutine is jobs.enqueue_feishu_sample_reverse_poll_audit
    )
    assert audit.hour == 18
    assert audit.minute == 30


def test_notification_dispatcher_enqueues_due_outbox_tasks() -> None:
    tenant_id = uuid4()
    event_id = uuid4()

    class NotificationService:
        async def list_due(self):
            return [(tenant_id, event_id, 2)]

    redis = FakeRedis()
    now = datetime(2026, 10, 8, 16, 20, tzinfo=UTC)
    count = asyncio.run(
        jobs.enqueue_due_sample_notifications(
            {
                "sample_notification_service": NotificationService(),
                "redis": redis,
                "now": now,
            }
        )
    )

    assert count == 1
    args, kwargs = redis.calls[0]
    assert args == ("send_sample_notification_job", str(tenant_id), str(event_id))
    assert kwargs["_job_id"] == f"sample-notification:{event_id}:3:202610081620"


def test_notification_dispatcher_is_disabled_without_sender() -> None:
    count = asyncio.run(
        jobs.enqueue_due_sample_notifications(
            {"sample_notification_service": None, "redis": FakeRedis()}
        )
    )

    assert count == 0


def test_notification_worker_holds_shop_lock_before_delivery() -> None:
    tenant_id, shop_id, event_id = uuid4(), uuid4(), uuid4()
    events = []

    class NotificationService:
        async def shop_id_for_event(self, actual_tenant_id, actual_event_id):
            assert actual_tenant_id == tenant_id
            assert actual_event_id == event_id
            events.append("scope")
            return shop_id

        async def deliver(self, actual_tenant_id, actual_event_id):
            assert actual_tenant_id == tenant_id
            assert actual_event_id == event_id
            events.append("deliver")
            return "sent"

    class Lock:
        @asynccontextmanager
        async def acquire(self, actual_tenant_id, actual_shop_id):
            assert (actual_tenant_id, actual_shop_id) == (tenant_id, shop_id)
            events.append("lock")
            yield True

    class AssignmentRecords:
        async def sync(self, **kwargs):
            assert kwargs == {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                "outbox_ids": frozenset({event_id}),
            }
            events.append("assignment_sync")

    result = asyncio.run(
        jobs.send_sample_notification_job(
            {
                "sample_notification_service": NotificationService(),
                "sample_shop_sync_lock": Lock(),
                "sample_assignment_record_service": AssignmentRecords(),
            },
            str(tenant_id),
            str(event_id),
        )
    )

    assert result == "sent"
    assert events == [
        "scope",
        "lock",
        "scope",
        "assignment_sync",
        "deliver",
        "assignment_sync",
    ]


def test_notification_worker_blocks_delivery_when_assignment_record_sync_fails() -> (
    None
):
    tenant_id, shop_id, event_id = uuid4(), uuid4(), uuid4()

    class NotificationService:
        async def shop_id_for_event(self, *_args):
            return shop_id

        async def deliver(self, *_args):
            raise AssertionError("notification must wait for the assignment record")

    class Lock:
        @asynccontextmanager
        async def acquire(self, *_args):
            yield True

    class AssignmentRecords:
        async def sync(self, **_kwargs):
            raise RuntimeError("assignment record sync failed")

    with pytest.raises(RuntimeError, match="assignment record sync failed"):
        asyncio.run(
            jobs.send_sample_notification_job(
                {
                    "sample_notification_service": NotificationService(),
                    "sample_shop_sync_lock": Lock(),
                    "sample_assignment_record_service": AssignmentRecords(),
                },
                str(tenant_id),
                str(event_id),
            )
        )


def test_notification_worker_retries_when_pipeline_holds_shop_lock() -> None:
    from arq import Retry

    tenant_id, shop_id, event_id = uuid4(), uuid4(), uuid4()

    class NotificationService:
        async def shop_id_for_event(self, *_args):
            return shop_id

        async def deliver(self, *_args):
            raise AssertionError("notification must wait for the shop pipeline")

    class Lock:
        @asynccontextmanager
        async def acquire(self, *_args):
            yield False

    with pytest.raises(Retry) as raised:
        asyncio.run(
            jobs.send_sample_notification_job(
                {
                    "sample_notification_service": NotificationService(),
                    "sample_shop_sync_lock": Lock(),
                    "sample_shop_lock_retry_seconds": 45,
                },
                str(tenant_id),
                str(event_id),
            )
        )

    assert raised.value.defer_score == 45_000


def test_notification_worker_and_minute_cron_are_registered() -> None:
    from erp_api.workers.sample_settings import SampleWorkerSettings

    functions = {
        function.name: function
        for function in SampleWorkerSettings.functions
        if hasattr(function, "name")
    }
    assert "send_sample_notification_job" in functions
    assert functions["send_sample_notification_job"].max_tries == 60
    assert jobs.enqueue_due_sample_notifications in SampleWorkerSettings.functions
    assert "cron(enqueue_due_sample_notifications" in inspect.getsource(
        SampleWorkerSettings
    )
