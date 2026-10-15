from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import recover_cross12_video_gap as recovery


def plan():
    return {"window_open": False, "shops": [{
        "shop_id": "5e1fed24-8268-5b5a-9ead-5efb862e7a51",
        "missing": [recovery.WINDOWS["creators"], recovery.WINDOWS["videos"]],
    }]}


@pytest.mark.asyncio
async def test_only_exact_window_is_exported_and_readback_required(monkeypatch):
    before = plan()
    after = deepcopy(before)
    after["shops"][0]["missing"] = [recovery.WINDOWS["videos"]]
    plans = iter([before, after])
    monkeypatch.setattr(recovery, "fetch_plan", lambda: next(plans))

    def choose(filtered, args):
        assert args.resource == "creators"
        assert filtered["shops"][0]["missing"] == [recovery.WINDOWS["creators"]]
        return filtered["shops"][0], filtered["shops"][0]["missing"][0], recovery.LABEL

    monkeypatch.setattr(recovery, "choose_window", choose)
    monkeypatch.setattr(recovery, "browser_work", lambda label: nullcontext())
    execute = AsyncMock(return_value="stored")
    monkeypatch.setattr(recovery, "execute_window", execute)

    async def priority(label, factory):
        assert label == "cross-border-12"
        return await factory()

    monkeypatch.setattr(recovery, "run_secondary", priority)
    await recovery.run(SimpleNamespace(resource="creators"))
    assert execute.await_count == 1


@pytest.mark.asyncio
async def test_sample_admission_failure_makes_no_export(monkeypatch):
    monkeypatch.setattr(recovery, "fetch_plan", plan)
    monkeypatch.setattr(recovery, "choose_window", lambda *_: None)
    execute = AsyncMock(side_effect=AssertionError("No export allowed"))
    monkeypatch.setattr(recovery, "execute_window", execute)
    await recovery.run(SimpleNamespace(resource="videos"))
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_scheduler_ownership_is_preserved(monkeypatch):
    monkeypatch.setattr(recovery, "fetch_plan", lambda: {"window_open": True})
    with pytest.raises(RuntimeError, match="Normal export scheduler owns"):
        await recovery.run(SimpleNamespace(resource="videos"))
