from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from erp_api.services.sample_notification_repository import (
    SampleNotificationRepository,
)
from erp_api.workers.sample_notification_jobs import send_sample_notification_job


def test_terminal_notification_skips_before_shop_lock() -> None:
    tenant_id, event_id = uuid4(), uuid4()

    class Notifications:
        async def shop_id_for_event(self, actual_tenant_id, actual_event_id):
            assert (actual_tenant_id, actual_event_id) == (tenant_id, event_id)

    class Lock:
        def acquire(self, *_args):
            raise AssertionError("terminal notification must not acquire shop lock")

    result = asyncio.run(
        send_sample_notification_job(
            {
                "sample_notification_service": Notifications(),
                "sample_shop_sync_lock": Lock(),
            },
            str(tenant_id),
            str(event_id),
        )
    )

    assert result.status == "skipped"
    assert result.event_id == event_id


def test_notification_scope_query_excludes_terminal_statuses() -> None:
    tenant_id, event_id = uuid4(), uuid4()
    captured = []

    class Session:
        async def scalar(self, statement):
            captured.append(statement)

    class Database:
        @asynccontextmanager
        async def system_session_factory(self):
            yield Session()

    repository = SampleNotificationRepository(Database())
    result = asyncio.run(repository.shop_id_for_event(tenant_id, event_id))

    assert result is None
    parameters = captured[0].compile().params
    assert {"pending", "retry_wait", "processing"} in (
        set(value) for value in parameters.values() if isinstance(value, (tuple, list))
    )


def test_notification_turning_terminal_while_waiting_for_lock_skips_sync() -> None:
    tenant_id, event_id, shop_id = uuid4(), uuid4(), uuid4()
    checks = []

    class Notifications:
        async def shop_id_for_event(self, *_args):
            checks.append(True)
            return shop_id if len(checks) == 1 else None

    class Lock:
        @asynccontextmanager
        async def acquire(self, *_args):
            yield True

    result = asyncio.run(
        send_sample_notification_job(
            {
                "sample_notification_service": Notifications(),
                "sample_shop_sync_lock": Lock(),
            },
            str(tenant_id),
            str(event_id),
        )
    )

    assert result.status == "skipped"
    assert len(checks) == 2
