"""A stalled external tab must not join or be closed by a sample collector."""

import pytest

from backend.app.services.sample_owned_cdp import (
    is_owned_attachment,
    safe_owned_command,
)


def test_external_page_is_not_attached_to_collector():
    event = {"method": "Target.attachedToTarget", "params": {
        "sessionId": "external-session", "targetInfo": {"targetId": "stalled"},
    }}
    assert not is_owned_attachment(event, "collector", set())
    event["params"]["targetInfo"]["targetId"] = "collector"
    assert is_owned_attachment(event, "collector", set())


def test_owned_subframes_remain_attached():
    event = {"sessionId": "owned-session", "params": {
        "sessionId": "frame-session", "targetInfo": {"targetId": "frame"},
    }}
    assert is_owned_attachment(event, "collector", {"owned-session"})


@pytest.mark.parametrize("method,params", [
    ("Browser.close", {}),
    ("Target.closeTarget", {"targetId": "external"}),
])
def test_browser_and_external_targets_cannot_be_closed(method, params):
    with pytest.raises(PermissionError):
        safe_owned_command({"method": method, "params": params}, "collector")


def test_collector_target_can_be_closed():
    command = {"method": "Target.closeTarget", "params": {"targetId": "collector"}}
    assert safe_owned_command(command, "collector") == command


def test_other_new_tabs_are_never_paused():
    command = {"method": "Target.setAutoAttach", "params": {
        "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True,
    }}
    assert safe_owned_command(command, "collector")["params"]["waitForDebuggerOnStart"] is False


def test_sample_attachment_keeps_existing_browser_download_settings():
    command = {"id": 5, "method": "Browser.setDownloadBehavior", "params": {"behavior": "allowAndName"}}
    assert safe_owned_command(command, "collector") is None
