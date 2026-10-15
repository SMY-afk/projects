"""Windowless collectors must keep diagnostic child consoles hidden."""

from types import SimpleNamespace

import pytest

from backend.app.services import hubstudio_cdp, hubstudio_cdp_ownership
from scripts import run_auto_affiliate_exports


@pytest.mark.parametrize("target", ["discovery", "ownership", "planner"])
def test_background_collector_subprocess_uses_no_window(monkeypatch, target):
    flags = []

    def runner(*_, **kwargs):
        flags.append(kwargs.get("creationflags", 0))
        return SimpleNamespace(returncode=1 if target == "planner" else 0, stdout="{}")

    monkeypatch.setattr(hubstudio_cdp.subprocess, "run", runner)
    monkeypatch.setattr(hubstudio_cdp.os, "name", "nt")
    monkeypatch.setattr(hubstudio_cdp.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    if target == "discovery":
        hubstudio_cdp.read_hubstudio_command_lines()
    elif target == "ownership":
        hubstudio_cdp_ownership._read_process_snapshot(62968, runner)
    else:
        with pytest.raises(RuntimeError, match="export planner failed"):
            run_auto_affiliate_exports.fetch_plan()
    assert flags == [0x08000000]
