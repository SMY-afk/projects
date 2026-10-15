import asyncio
import inspect
from uuid import uuid4

from erp_api import main as api_main
from scripts import run_hubstudio_affiliate_watch as worker


def test_one_shop_failure_does_not_stop_other_shop_listeners(monkeypatch) -> None:
    failed_shop = uuid4()
    healthy_shops = [uuid4(), uuid4()]
    completed = []

    async def run_listener(_cdp_url, _tenant_id, shop_id, _retry_delays):
        if shop_id == failed_shop:
            raise RuntimeError("session expired")
        completed.append(shop_id)
        raise RuntimeError("stop test worker")

    monkeypatch.setattr(worker, "run_listener", run_listener)

    asyncio.run(
        worker.run_watch(
            uuid4(),
            [failed_shop, *healthy_shops],
            (30.0, 60.0, 300.0),
            ["http://127.0.0.1:51001"] * 3,
        )
    )

    assert completed == healthy_shops


def test_fastapi_process_does_not_import_or_start_the_collector_worker() -> None:
    source = inspect.getsource(api_main)

    assert "run_hubstudio_affiliate_watch" not in source
    assert "tiktok_affiliate_listener" not in source
    assert "playwright" not in source.casefold()


def test_wmi_workaround_is_limited_to_python_313() -> None:
    source = inspect.getsource(worker)

    assert 'os.name == "nt" and sys.version_info >= (3, 13)' in source


def test_explicit_cdp_urls_are_aligned_with_shop_listeners(monkeypatch) -> None:
    shop_ids = [uuid4(), uuid4()]
    calls = []

    async def run_listener(cdp_url, _tenant_id, shop_id, _retry_delays):
        calls.append((shop_id, cdp_url))
        raise RuntimeError("stop test worker")

    monkeypatch.setattr(worker, "run_listener", run_listener)

    asyncio.run(
        worker.run_watch(
            uuid4(),
            shop_ids,
            (30.0, 60.0, 300.0),
            ["http://127.0.0.1:51001", "http://127.0.0.1:51002"],
        )
    )

    assert calls == list(
        zip(
            shop_ids,
            ["http://127.0.0.1:51001", "http://127.0.0.1:51002"],
            strict=True,
        )
    )


def test_worker_auto_discovers_shop_browsers(monkeypatch) -> None:
    shop_id = uuid4()
    calls = []

    async def run_listener(cdp_url, _tenant_id, current_shop_id, _retry_delays):
        calls.append((current_shop_id, cdp_url))
        raise RuntimeError("stop test worker")

    monkeypatch.setattr(worker, "run_listener", run_listener)
    asyncio.run(worker.run_watch(uuid4(), [shop_id], (30.0,), None))

    assert calls == [(shop_id, None)]


def test_retry_exhaustion_restarts_shop_worker(monkeypatch) -> None:
    calls = []
    sleeps = []

    async def run_listener(*args):
        calls.append(args)
        if len(calls) > 1:
            raise RuntimeError("stop test worker")

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(worker, "run_listener", run_listener)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)

    asyncio.run(
        worker._run_shop_worker(
            None,
            uuid4(),
            uuid4(),
            (30.0, 60.0, 300.0),
            restart_delay_seconds=120.0,
        )
    )

    assert len(calls) == 2
    assert sleeps == [120.0]
