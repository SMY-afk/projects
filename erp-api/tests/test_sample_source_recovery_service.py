from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_source_policy import (
    SAMPLE_APPLICATION_SCOPE,
    SampleShopAccess,
)
from erp_api.services.sample_source_recovery_service import (
    SampleSourceRecoveryError,
    SampleSourceRecoveryService,
)


class Repository:
    def __init__(self, accesses: list[SampleShopAccess | None]) -> None:
        self.accesses = iter(accesses)

    async def get_shop_access(self, tenant_id, shop_id):
        return next(self.accesses)

    async def list_recovery_candidates(self):
        return [(uuid4(), uuid4())]


class SyncService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    async def sync(self, tenant_id, shop_id, **kwargs):
        self.calls.append((tenant_id, shop_id, kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(status="succeeded")


def _access(
    *,
    scope: bool = True,
    cdp_at: datetime | None = None,
    official_at: datetime | None = None,
) -> SampleShopAccess:
    scopes = frozenset({SAMPLE_APPLICATION_SCOPE}) if scope else frozenset()
    return SampleShopAccess(
        "platform-1",
        scopes,
        latest_cdp_at=cdp_at,
        latest_official_reconciliation_at=official_at,
    )


def test_recovery_runs_full_reconciliation_before_disabling_cdp() -> None:
    cdp_at = datetime(2026, 9, 10, tzinfo=UTC)
    repository = Repository(
        [
            _access(cdp_at=cdp_at),
            _access(cdp_at=cdp_at, official_at=cdp_at + timedelta(minutes=1)),
        ]
    )
    sync = SyncService()
    disabled = []

    async def disable(tenant_id, shop_id, reason):
        disabled.append((tenant_id, shop_id, reason))

    tenant_id = uuid4()
    shop_id = uuid4()
    result = asyncio.run(
        SampleSourceRecoveryService(repository, sync).recover(
            tenant_id, shop_id, disable_cdp=disable
        )
    )

    assert result.status == "cdp_disabled"
    assert sync.calls == [(tenant_id, shop_id, {"mode": "full", "status": None})]
    assert disabled == [
        (tenant_id, shop_id, "official_reconciliation_complete")
    ]


def test_recovery_failure_does_not_disable_cdp() -> None:
    cdp_at = datetime(2026, 9, 10, tzinfo=UTC)
    sync = SyncService(error=RuntimeError("official sync failed"))
    disabled = []

    async def disable(*args):
        disabled.append(args)

    with pytest.raises(RuntimeError, match="official sync failed"):
        asyncio.run(
            SampleSourceRecoveryService(
                Repository([_access(cdp_at=cdp_at)]), sync
            ).recover(uuid4(), uuid4(), disable_cdp=disable)
        )

    assert disabled == []


def test_recovery_rejects_a_reconciliation_that_does_not_cover_latest_cdp() -> None:
    cdp_at = datetime(2026, 9, 10, tzinfo=UTC)
    repository = Repository(
        [
            _access(cdp_at=cdp_at),
            _access(cdp_at=cdp_at, official_at=cdp_at - timedelta(seconds=1)),
        ]
    )

    with pytest.raises(SampleSourceRecoveryError) as captured:
        asyncio.run(
            SampleSourceRecoveryService(repository, SyncService()).recover(
                uuid4(), uuid4()
            )
        )

    assert captured.value.code == "reconciliation_not_covering_cdp"


def test_missing_scope_does_not_run_reconciliation() -> None:
    sync = SyncService()
    result = asyncio.run(
        SampleSourceRecoveryService(
            Repository([_access(scope=False)]), sync
        ).recover(uuid4(), uuid4())
    )

    assert result.status == "scope_missing"
    assert sync.calls == []
