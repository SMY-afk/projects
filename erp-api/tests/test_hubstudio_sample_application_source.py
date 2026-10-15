from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from erp_api.services.hubstudio_sample_application_source import (
    HubStudioEnvironmentSnapshot,
    HubStudioSampleApplicationSource,
    HubStudioSamplePreflightError,
    HubStudioSampleTarget,
)

CDP_URL = "http://127.0.0.1:55111"


class Policy:
    def __init__(self) -> None:
        self.calls = []

    async def require_hubstudio_fallback(self, **kwargs):
        self.calls.append(kwargs)


def _target(**changes) -> HubStudioSampleTarget:
    target = HubStudioSampleTarget(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        environment_id="1809223023",
        platform_shop_id="platform-1",
        cdp_url=CDP_URL,
        official_access_state="missing_scope",
    )
    return replace(target, **changes)


def _source(
    policy: Policy,
    *,
    environment: HubStudioEnvironmentSnapshot | None = None,
    page_shop_ids=frozenset({"platform-1"}),
):
    snapshot = environment or HubStudioEnvironmentSnapshot(
        environment_id="1809223023", running=True, cdp_url=CDP_URL
    )

    async def environment_probe(_environment_id):
        return snapshot

    async def endpoint_probe(_url):
        return True

    async def page_shop_reader(_url):
        return page_shop_ids

    return HubStudioSampleApplicationSource(
        policy,
        environment_probe,
        ownership_checker=lambda url: url,
        endpoint_probe=endpoint_probe,
        page_shop_reader=page_shop_reader,
    )


def test_preflight_requires_all_explicit_shop_binding_fields() -> None:
    policy = Policy()
    source = _source(policy)

    with pytest.raises(HubStudioSamplePreflightError) as captured:
        asyncio.run(source.preflight(_target(environment_id="")))

    assert captured.value.code == "invalid_binding"
    assert policy.calls == []


@pytest.mark.parametrize("cdp_url", ["http://127.0.0.1:6873", "http://127.0.0.1:19222"])
def test_preflight_rejects_control_api_and_generic_chrome_ports(cdp_url: str) -> None:
    with pytest.raises(HubStudioSamplePreflightError) as captured:
        asyncio.run(_source(Policy()).preflight(_target(cdp_url=cdp_url)))
    assert captured.value.code == "invalid_binding"


def test_preflight_validates_policy_environment_process_port_and_page_shop() -> None:
    policy = Policy()
    source = _source(policy)

    result = asyncio.run(source.preflight(_target()))

    assert result.normalized_cdp_url == CDP_URL
    assert policy.calls[0]["platform_shop_id"] == "platform-1"
    assert policy.calls[0]["official_access_state"] == "missing_scope"


def test_preflight_rejects_environment_to_cdp_mismatch() -> None:
    environment = HubStudioEnvironmentSnapshot(
        environment_id="1809223023",
        running=True,
        cdp_url="http://127.0.0.1:55112",
    )
    with pytest.raises(HubStudioSamplePreflightError) as captured:
        asyncio.run(_source(Policy(), environment=environment).preflight(_target()))
    assert captured.value.code == "environment_cdp_mismatch"


@pytest.mark.parametrize(
    "page_shop_ids",
    [frozenset(), frozenset({"platform-2"}), frozenset({"platform-1", "platform-2"})],
)
def test_preflight_rejects_zero_multiple_or_wrong_page_shops(page_shop_ids) -> None:
    source = _source(Policy(), page_shop_ids=page_shop_ids)
    with pytest.raises(HubStudioSamplePreflightError) as captured:
        asyncio.run(source.preflight(_target()))
    assert captured.value.code == "page_shop_mismatch"


def test_sample_source_does_not_import_generic_browser_or_feishu_clients() -> None:
    source = Path(
        "src/erp_api/services/hubstudio_sample_application_source.py"
    ).read_text(encoding="utf-8")
    assert "async_playwright" not in source
    assert "connect_over_cdp" not in source
    assert "feishu" not in source.casefold()
