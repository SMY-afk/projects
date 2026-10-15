from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services import sample_business_readiness as readiness_module
from erp_api.services.sample_shop_pipeline_service import SampleShopPipelineService
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


@pytest.mark.asyncio
async def test_business_readiness_blocks_all_external_work_after_local_pending_gate():
    tenant_id, shop_id, application_id = uuid4(), uuid4(), uuid4()
    calls = []

    class WorkGate:
        async def has_work(self, **_kwargs):
            calls.append("local_gate")
            return True

    class Readiness:
        async def require_ready(self, **scope):
            assert scope == {"tenant_id": tenant_id, "shop_id": shop_id}
            calls.append("readiness")
            raise RuntimeError("five_shop_source_incomplete")

    class Feishu:
        async def sync(self, **_kwargs):
            raise AssertionError("Feishu must not be called before readiness")

    class Cooperation:
        async def evaluate(self, *_args, **_kwargs):
            raise AssertionError("Cooperation tables must not be read")

    async def profile_capture():
        raise AssertionError("Profile capture must not run")

    pipeline = SampleShopPipelineService(
        object(),
        Feishu(),
        cooperation_precheck=Cooperation(),
        work_gate=WorkGate(),
        business_readiness=Readiness(),
    )
    with pytest.raises(RuntimeError, match="five_shop_source_incomplete"):
        await pipeline.complete_after_source(
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_type="hubstudio_cdp",
            source_results=(SimpleNamespace(application_ids=(application_id,)),),
            profile_capture=profile_capture,
        )
    assert calls == ["local_gate", "readiness"]


@pytest.mark.asyncio
async def test_business_readiness_is_not_called_without_pending_work():
    class WorkGate:
        async def has_work(self, **_kwargs):
            return False

    class Readiness:
        async def require_ready(self, **_scope):
            raise AssertionError("idle cycle must not probe all five shops")

    result = await SampleShopPipelineService(
        object(),
        object(),
        work_gate=WorkGate(),
        business_readiness=Readiness(),
    ).complete_after_source(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        source_type="hubstudio_cdp",
        source_results=(SimpleNamespace(application_ids=(uuid4(),)),),
    )
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_runtime_readiness_accepts_successful_daily_sync_without_live_resync(
    monkeypatch,
):
    report = {
        "sample_all_ok": True,
        "daily_local_all_ready": True,
        "shops": [
            {
                "shop": shop,
                "sample_ok": True,
                "available_dates": {
                    "creators": "2026-10-06",
                    "videos": "2026-10-06",
                    "liveAccounts": "2026-10-06",
                },
            }
            for shop in SHOPS
        ],
    }

    async def build_report(_sample_stale_seconds):
        return report

    async def daily_sync_succeeded(_batch_date):
        return True

    checker = readiness_module.SampleBusinessReadiness()
    monkeypatch.setattr(checker, "_require_readyz", lambda: _noop())
    monkeypatch.setattr(checker, "_daily_sync_succeeded", daily_sync_succeeded)
    monkeypatch.setattr(readiness_module, "build_report", build_report)
    monkeypatch.setattr(
        readiness_module, "_valid_creator_batch_date", lambda *_args: date(2026, 10, 8)
    )
    await checker.require_ready(tenant_id=TENANT_ID, shop_id=SHOPS["cross-border-3"])


@pytest.mark.asyncio
async def test_worker_readiness_checks_own_config_schema_and_heartbeat(monkeypatch):
    calls = []

    class Database:
        def __init__(self, url):
            calls.append(("database", url))

        async def dispose(self):
            calls.append("dispose")

    async def probe(database, redis_url, *, sample_sync_enabled):
        calls.append(("probe", database, redis_url, sample_sync_enabled))
        return {
            "database": "ok",
            "redis": "ok",
            "sample_sync_config": "ok",
            "sample_schema": "ok",
            "sample_worker": "ok",
        }

    monkeypatch.setattr(readiness_module, "Database", Database, raising=False)
    monkeypatch.setattr(readiness_module, "probe_dependencies", probe, raising=False)
    monkeypatch.setattr(
        readiness_module,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://test", redis_url="redis://test"
        ),
    )
    monkeypatch.setattr(
        readiness_module,
        "_sample_sync_config_status",
        lambda _settings: "ok",
        raising=False,
    )
    await readiness_module.SampleBusinessReadiness._require_readyz()
    assert calls[0] == ("database", "postgresql://test")
    assert calls[1][0] == "probe"
    assert calls[1][2:] == ("redis://test", True)
    assert calls[-1] == "dispose"


def test_valid_creator_batch_does_not_switch_before_daily_table_write_time():
    assert readiness_module._valid_creator_batch_date(
        datetime(2026, 10, 8, 15, 49, tzinfo=UTC)
    ) == date(2026, 10, 7)
    assert readiness_module._valid_creator_batch_date(
        datetime(2026, 10, 8, 15, 50, tzinfo=UTC)
    ) == date(2026, 10, 7)
    assert readiness_module._valid_creator_batch_date(
        datetime(2026, 10, 8, 17, 29, 59, tzinfo=UTC)
    ) == date(2026, 10, 7)
    assert readiness_module._valid_creator_batch_date(
        datetime(2026, 10, 8, 17, 30, tzinfo=UTC)
    ) == date(2026, 10, 8)


async def _noop():
    return None
