import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import scripts.run_ziniao_sample_profile_watch as profile_watcher_module
import scripts.run_ziniao_sample_watch as watcher_module
from backend.app.services import sample_review_pagination as pagination_module
from erp_api.services import ziniao_sample_feishu_sync as ziniao_sync_module
from erp_api.services.ziniao_webdriver_client import ZiniaoBrowserSession


def test_ziniao_sample_time_watcher_does_not_capture_creator_details() -> None:
    source = Path("scripts/run_ziniao_sample_watch.py").read_text(encoding="utf-8")
    for forbidden in (
        "TikTokSampleCreatorDetails",
        "profile_collector",
        "creator/marketplace/profile",
        "affiliate/creator/detail",
    ):
        assert forbidden not in source


def test_ziniao_sample_starter_uses_time_only_watcher() -> None:
    source = Path("scripts/start-ziniao-sample-profile-watch.ps1").read_text(
        encoding="utf-8"
    )
    assert "scripts.run_ziniao_sample_watch" in source
    assert "scripts.run_ziniao_sample_profile_watch" not in source


def test_resolves_actual_cdp_port_when_ziniao_reports_stale_port(monkeypatch) -> None:
    monkeypatch.setattr(
        watcher_module,
        "_ziniao_listening_ports",
        lambda: [56057],
    )

    async def read_shop_ids(url: str):
        if url.endswith(":56057"):
            return frozenset({"shop-one"})
        raise OSError("stale port")

    monkeypatch.setattr(watcher_module, "read_cdp_platform_shop_ids", read_shop_ids)

    port = asyncio.run(watcher_module._resolve_cdp_port(56076, "shop-one"))

    assert port == 56057


def test_feishu_failure_does_not_stop_time_enrichment_listener(monkeypatch) -> None:
    application_id = uuid4()
    events = []

    class FailingFeishuSync:
        async def sync(self, **_kwargs):
            raise RuntimeError("temporary Feishu failure")

    monkeypatch.setattr(
        ziniao_sync_module,
        "capture_log",
        lambda event, **values: events.append((event, values)),
    )

    result = asyncio.run(
        watcher_module._sync_enriched_applications(
            FailingFeishuSync(),
            tenant_id=uuid4(),
            shop_id=uuid4(),
            application_ids=frozenset({application_id}),
        )
    )

    assert result == {
        "feishu_created": 0,
        "feishu_updated": 0,
        "feishu_deleted": 0,
        "feishu_delete_pending": 0,
        "feishu_error_type": "RuntimeError",
    }
    assert events[0][0] == "ziniao_sample_time_feishu_sync_failed"


def test_time_enrichment_continues_with_assignment_pipeline() -> None:
    application_id = uuid4()
    events = []

    class FeishuSync:
        async def sync(self, **_kwargs):
            events.append("feishu")
            return SimpleNamespace(created_count=1, updated_count=0)

    class Pipeline:
        async def complete_after_source(self, **kwargs):
            events.append("pipeline")
            assert kwargs["source_type"] == "official_api"
            assert kwargs["source_results"][0].application_ids == frozenset(
                {application_id}
            )
            return SimpleNamespace(
                feishu_result=SimpleNamespace(created_count=1, updated_count=0)
            )

    result = asyncio.run(
        watcher_module._sync_enriched_applications(
            FeishuSync(),
            tenant_id=uuid4(),
            shop_id=uuid4(),
            application_ids=frozenset({application_id}),
            post_source_service=Pipeline(),
        )
    )

    assert events == ["pipeline"]
    assert result == {
        "feishu_created": 1,
        "feishu_updated": 0,
        "feishu_deleted": 0,
        "feishu_delete_pending": 0,
    }


def test_time_enrichment_holds_shop_lock_for_assignment_pipeline() -> None:
    application_id = uuid4()
    tenant_id = uuid4()
    shop_id = uuid4()
    events = []

    class ShopLock:
        @asynccontextmanager
        async def acquire(self, received_tenant_id, received_shop_id):
            assert (received_tenant_id, received_shop_id) == (tenant_id, shop_id)
            events.append("lock-acquired")
            yield True
            events.append("lock-released")

    class Pipeline:
        async def complete_after_source(self, **_kwargs):
            events.append("pipeline")
            return SimpleNamespace(
                feishu_result=SimpleNamespace(created_count=0, updated_count=1)
            )

    result = asyncio.run(
        watcher_module._sync_enriched_applications(
            object(),
            tenant_id=tenant_id,
            shop_id=shop_id,
            application_ids=frozenset({application_id}),
            post_source_service=Pipeline(),
            shop_sync_lock=ShopLock(),
        )
    )

    assert events == ["lock-acquired", "pipeline", "lock-released"]
    assert result["feishu_updated"] == 1


def test_skipped_time_pipeline_does_not_read_feishu_for_group_cleanup(
    monkeypatch,
) -> None:
    events = []

    class Pipeline:
        async def complete_after_source(self, **_kwargs):
            events.append("pipeline")
            return SimpleNamespace(status="skipped", feishu_result=None)

    async def cleanup(**_kwargs):
        events.append("cleanup")
        raise AssertionError("Feishu cleanup must wait for a due pipeline")

    monkeypatch.setattr(ziniao_sync_module, "delete_grouped_duplicate_records", cleanup)
    result = asyncio.run(
        watcher_module._sync_enriched_applications(
            object(),
            tenant_id=uuid4(),
            shop_id=uuid4(),
            application_ids=frozenset({uuid4()}),
            obsolete_platform_application_ids=frozenset({"obsolete-request"}),
            feishu=object(),
            mappings=object(),
            post_source_service=Pipeline(),
        )
    )

    assert events == ["pipeline"]
    assert result["feishu_created"] == 0
    assert result["feishu_updated"] == 0
    assert result["feishu_deleted"] == 0


def test_time_enrichment_skips_pipeline_when_shop_lock_is_busy() -> None:
    events = []

    class ShopLock:
        @asynccontextmanager
        async def acquire(self, _tenant_id, _shop_id):
            yield False

    class Pipeline:
        async def complete_after_source(self, **_kwargs):
            events.append("pipeline")

    result = asyncio.run(
        watcher_module._sync_enriched_applications(
            object(),
            tenant_id=uuid4(),
            shop_id=uuid4(),
            application_ids=frozenset({uuid4()}),
            post_source_service=Pipeline(),
            shop_sync_lock=ShopLock(),
        )
    )

    assert events == []
    assert result == {
        "feishu_created": 0,
        "feishu_updated": 0,
        "feishu_deleted": 0,
        "feishu_delete_pending": 0,
        "feishu_deferred_reason": "shop_sync_busy",
    }


def test_ziniao_sample_watcher_wires_shared_shop_lock() -> None:
    source = Path("scripts/run_ziniao_sample_watch.py").read_text(encoding="utf-8")

    assert "SampleShopSyncLock(database)" in source
    assert "shop_sync_lock=shop_sync_lock" in source


def test_ziniao_sample_watcher_decouples_capture_from_business_processing() -> None:
    source = Path("scripts/run_ziniao_sample_watch.py").read_text(encoding="utf-8")

    assert "capture_review_batch_from_page" in source
    assert "HubStudioSampleNetworkListener" not in source
    assert "capture_all_review_pages" not in source


def test_ziniao_sample_watcher_captures_every_review_page(monkeypatch) -> None:
    completed = asyncio.Event()
    completed.set()
    next_results = iter((True, False))

    class Listener:
        def __init__(self) -> None:
            self.waits = 0

        async def wait_for_pending(self) -> None:
            self.waits += 1

    async def next_page(_page) -> bool:
        result = next(next_results)
        if result:
            asyncio.get_running_loop().call_soon(completed.set)
        return result

    listener = Listener()
    monkeypatch.setattr(pagination_module, "next_sample_page", next_page)

    pages = asyncio.run(
        pagination_module.capture_all_review_pages(
            object(), completed, listener, timeout_seconds=1
        )
    )

    assert pages == 2
    assert listener.waits == 2


def test_next_cycle_runs_after_official_five_minute_poll_window() -> None:
    assert watcher_module._next_cycle_delay(600.0, 300.0, 90.0) == 90.0
    assert watcher_module._next_cycle_delay(689.0, 300.0, 90.0) == 1.0
    assert watcher_module._next_cycle_delay(691.0, 300.0, 90.0) == 299.0


def test_profile_capture_replaces_stale_ziniao_cdp_port(monkeypatch) -> None:
    session = ZiniaoBrowserSession(56076, "131.0", "Chromium", Path("browser"))

    async def resolve(port: int, platform_shop_id: str) -> int:
        assert (port, platform_shop_id) == (56076, "shop-one")
        return 56057

    monkeypatch.setattr(profile_watcher_module, "_resolve_cdp_port", resolve)

    resolved = asyncio.run(
        profile_watcher_module._resolved_browser_session(session, "shop-one")
    )

    assert resolved.debugging_port == 56057
    assert resolved.core_version == session.core_version
