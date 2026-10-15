import json
from types import SimpleNamespace as Row

import pytest

from scripts.local_capture_guard import CaptureGuardError
from scripts.local_sample_metadata_capture import GuardedResponse
from scripts.local_sample_metadata_owned_cdp import (
    ExistingTargetSocket,
    require_existing_target,
)


def registry(tmp_path, *, ownership="collector_created", target="target-one"):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"ownership": ownership}))
    return Row(path=path, resolve=lambda _targets: target)


def test_missing_or_external_registry_never_creates_target(tmp_path):
    with pytest.raises(RuntimeError, match="existing_owned"):
        require_existing_target(registry(tmp_path, target=None), [])
    with pytest.raises(RuntimeError, match="ownership"):
        require_existing_target(registry(tmp_path, ownership="operator_approved_external"), [])


@pytest.mark.asyncio
async def test_proxy_forbids_new_page_close_and_other_target_activation():
    calls = []

    class Socket:
        async def send(self, message):
            calls.append(json.loads(message))

    wrapper = ExistingTargetSocket(Socket(), "one")
    for method, params in [
        ("Target.createTarget", {"url": "about:blank"}), ("Browser.close", {}),
        ("Target.closeTarget", {"targetId": "one"}),
        ("Target.activateTarget", {"targetId": "other"}),
    ]:
        with pytest.raises(PermissionError):
            await wrapper.send(json.dumps({"method": method, "params": params}))
    await wrapper.send(json.dumps({"method": "Target.getTargetInfo", "params": {"targetId": "one"}}))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_raw_response_rejects_foreign_host_shop_or_frame(monkeypatch):
    page = Row(url="https://affiliate-us.tiktok.com/affiliate/sample/sample-request?shop_id=9136806951995371293")
    request = Row(frame=Row(url=page.url), post_data='{"shop_id":"9136806951995371293"}')

    class Response:
        url = "https://affiliate-us.tiktok.com/api/v1/affiliate/sample/group/list"

        async def json(self):
            return {"data": {"shop_id": "another"}}

    response = Response()
    response.request = request
    monkeypatch.setattr("scripts.local_sample_metadata_capture.verify_page", lambda *_: _ok())
    with pytest.raises(RuntimeError, match="response_identity"):
        await GuardedResponse(response, page, "endpoint").json()


async def _ok():
    return None


@pytest.mark.parametrize("status", [401, 403])
def test_auth_response_has_stable_security_pause_code(status):
    response = GuardedResponse(Row(status=status), None, "endpoint")
    with pytest.raises(CaptureGuardError, match="session_expired"):
        _ = response.status
