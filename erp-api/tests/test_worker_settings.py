from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

from erp_api.workers import settings as worker_settings


def test_worker_startup_configures_structured_logging(monkeypatch):
    configured_levels: list[str] = []
    catchup_database_urls: list[str] = []
    async def enqueue_catchup(context: dict[str, object]) -> int:
        database = context["database"]
        catchup_database_urls.append(database.url)
        return 0

    app_module = ModuleType("erp_api.main")
    app_module.build_order_services = lambda settings, database: {}
    app_module.build_analytics_services = lambda settings, database: {}
    app_module.build_product_services = lambda settings, database: {
        "product_sync_service": "product-service"
    }
    fake_settings = SimpleNamespace(
        log_level="WARNING",
        database_url="postgresql+asyncpg://example.invalid/erp",
        tiktok_analytics_job_max_tries=5,
        tiktok_webhook_signing_secret=None,
        order_pii_encryption_key=None,
    )

    monkeypatch.setitem(sys.modules, "erp_api.main", app_module)
    monkeypatch.setattr(worker_settings, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(
        worker_settings, "configure_logging", configured_levels.append, raising=False
    )
    monkeypatch.setattr(
        worker_settings, "Database", lambda url: SimpleNamespace(url=url)
    )
    monkeypatch.setattr(
        worker_settings,
        "enqueue_scheduled_affiliate_creator_syncs",
        enqueue_catchup,
    )
    monkeypatch.setattr(
        worker_settings,
        "enqueue_scheduled_affiliate_video_syncs",
        enqueue_catchup,
    )
    monkeypatch.setattr(
        worker_settings,
        "enqueue_scheduled_bestseller_syncs",
        enqueue_catchup,
    )

    context: dict[str, object] = {}
    asyncio.run(worker_settings.startup(context))

    assert configured_levels == ["WARNING"]
    assert context["analytics_sync_max_tries"] == 5
    assert context["product_sync_service"] == "product-service"
    assert catchup_database_urls == [
        "postgresql+asyncpg://example.invalid/erp",
    ]
