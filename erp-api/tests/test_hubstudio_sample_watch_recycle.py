import asyncio
from types import SimpleNamespace

from backend.app.services.hubstudio_sample_watch import run_hubstudio_sample_watch


def test_sample_watcher_recycles_only_after_completed_cycles(monkeypatch) -> None:
    calls = []
    attached_contexts = [object()]

    class Attached:
        def __init__(self):
            self.contexts = attached_contexts

        def on(self, event, _callback):
            assert event == "disconnected"

    class Listener:
        is_stopped = False
        stop_reason = None

        def __init__(self, *_args, **_kwargs):
            pass

        def attach(self, contexts):
            assert contexts == attached_contexts

        async def wait_for_pending(self):
            pass

    async def connect(_playwright, _url):
        return Attached()

    async def cycle(*_args):
        calls.append("cycle")
        return "succeeded"

    async def processing(*_args):
        calls.append("processing")
        return True

    monkeypatch.setattr(
        "backend.app.services.hubstudio_sample_watch.connect_attached_hubstudio_browser",
        connect,
    )
    monkeypatch.setattr(
        "backend.app.services.hubstudio_sample_watch.HubStudioSampleNetworkListener",
        Listener,
    )
    monkeypatch.setattr(
        "backend.app.services.hubstudio_sample_watch._run_cycle", cycle
    )
    monkeypatch.setattr(
        "backend.app.services.hubstudio_sample_watch._wait_for_processing",
        processing,
    )
    monkeypatch.setattr(
        "backend.app.services.hubstudio_sample_watch._log_cycle",
        lambda *_args: None,
    )
    preflight = SimpleNamespace(
        target=SimpleNamespace(), normalized_cdp_url="http://127.0.0.1:57031"
    )
    result = asyncio.run(
        run_hubstudio_sample_watch(
            playwright=object(),
            source=object(),
            preflight=preflight,
            ingest_service=object(),
            profile_target_provider=object(),
            profile_collector=object(),
            feishu_sync_service=object(),
            interval_seconds=0.001,
            max_cycles=2,
        )
    )

    assert result == "recycle"
    assert calls == ["cycle", "processing", "cycle", "processing"]
