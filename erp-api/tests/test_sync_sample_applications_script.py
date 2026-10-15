from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import sync_sample_applications as script


class FakeDatabase:
    def __init__(self, shop_id) -> None:
        self.shop_id = shop_id
        self.disposed = False

    @asynccontextmanager
    async def system_session_factory(self):
        yield self

    async def scalar(self, _statement):
        return self.shop_id

    async def dispose(self):
        self.disposed = True


def test_cli_requires_exact_scope_source_mode_and_action() -> None:
    with pytest.raises(SystemExit):
        script._arguments([])
    tenant_id, shop_id = uuid4(), uuid4()
    args = script._arguments(
        [
            "--tenant-id",
            str(tenant_id),
            "--shop-id",
            str(shop_id),
            "--source-type",
            "official_api",
            "--mode",
            "full",
            "--dry-run",
        ]
    )

    assert args.tenant_id == tenant_id
    assert args.shop_id == shop_id
    assert args.dry_run is True
    assert not hasattr(args, "all_shops")


def test_internal_runner_rejects_missing_explicit_action() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(
            script._run(
                SimpleNamespace(
                    tenant_id=uuid4(),
                    shop_id=uuid4(),
                    source_type="official_api",
                    mode="active",
                    dry_run=False,
                    enqueue=False,
                )
            )
        )


def test_dry_run_validates_only_the_named_shop_without_queueing(monkeypatch) -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    database = FakeDatabase(shop_id)
    monkeypatch.setattr(script, "get_settings", lambda: SimpleNamespace(database_url="db"))
    monkeypatch.setattr(script, "Database", lambda _url: database)

    result = asyncio.run(
        script._run(
            SimpleNamespace(
                tenant_id=tenant_id,
                shop_id=shop_id,
                source_type="hubstudio_cdp",
                mode="full",
                dry_run=True,
                enqueue=False,
            )
        )
    )

    assert result["status"] == "dry_run"
    assert result["shop_id"] == str(shop_id)
    assert database.disposed is True


def test_enqueue_targets_only_the_sample_queue_and_named_shop(monkeypatch) -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    database = FakeDatabase(shop_id)

    class Queue:
        def __init__(self) -> None:
            self.calls = []

        async def enqueue_job(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return object()

        async def aclose(self):
            return None

    queue = Queue()

    async def create_queue(*_args, **kwargs):
        assert kwargs["default_queue_name"] == "arq:sample"
        return queue

    monkeypatch.setattr(
        script,
        "get_settings",
        lambda: SimpleNamespace(database_url="db", redis_url="redis://localhost"),
    )
    monkeypatch.setattr(script, "Database", lambda _url: database)
    monkeypatch.setattr(script, "create_pool", create_queue)

    result = asyncio.run(
        script._run(
            SimpleNamespace(
                tenant_id=tenant_id,
                shop_id=shop_id,
                source_type="official_api",
                mode="full",
                dry_run=False,
                enqueue=True,
            )
        )
    )

    assert result["status"] == "queued"
    args, _kwargs = queue.calls[0]
    assert args[:3] == (
        "reconcile_sample_applications_job",
        str(tenant_id),
        str(shop_id),
    )
