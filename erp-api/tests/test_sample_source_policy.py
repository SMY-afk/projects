from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.sample_source_policy import (
    SAMPLE_APPLICATION_SCOPE,
    SampleShopAccess,
    SampleSourcePolicy,
    SampleSourcePolicyError,
)


class Repository:
    def __init__(self, access: SampleShopAccess | None) -> None:
        self.access = access

    async def get_shop_access(self, tenant_id, shop_id):
        return self.access


def _require(policy, *, state="missing_scope", platform_shop_id="platform-1"):
    return policy.require_hubstudio_fallback(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        platform_shop_id=platform_shop_id,
        official_access_state=state,
    )


def test_cdp_requires_explicit_stage0_missing_scope_result() -> None:
    policy = SampleSourcePolicy(Repository(SampleShopAccess("platform-1", frozenset())))
    with pytest.raises(SampleSourcePolicyError) as captured:
        asyncio.run(_require(policy, state="timeout"))
    assert captured.value.code == "stage0_not_confirmed"


def test_cdp_is_refused_when_official_sample_api_scope_exists() -> None:
    policy = SampleSourcePolicy(
        Repository(
            SampleShopAccess("platform-1", frozenset({SAMPLE_APPLICATION_SCOPE}))
        )
    )
    with pytest.raises(SampleSourcePolicyError) as captured:
        asyncio.run(_require(policy))
    assert captured.value.code == "official_api_available"


def test_cdp_requires_exact_erp_platform_shop_binding() -> None:
    policy = SampleSourcePolicy(Repository(SampleShopAccess("platform-2", frozenset())))
    with pytest.raises(SampleSourcePolicyError) as captured:
        asyncio.run(_require(policy))
    assert captured.value.code == "platform_shop_mismatch"


def test_cdp_accepts_confirmed_missing_scope_for_exact_shop() -> None:
    policy = SampleSourcePolicy(
        Repository(SampleShopAccess("platform-1", frozenset({"orders.read"})))
    )
    asyncio.run(_require(policy))


def test_cdp_remains_available_while_official_reconciliation_is_pending() -> None:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    policy = SampleSourcePolicy(
        Repository(
            SampleShopAccess(
                "platform-1",
                frozenset({SAMPLE_APPLICATION_SCOPE}),
                latest_cdp_at=now,
            )
        )
    )

    asyncio.run(_require(policy))


def test_cdp_is_refused_after_official_full_reconciliation_covers_it() -> None:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    policy = SampleSourcePolicy(
        Repository(
            SampleShopAccess(
                "platform-1",
                frozenset({SAMPLE_APPLICATION_SCOPE}),
                latest_cdp_at=now,
                latest_official_reconciliation_at=now + timedelta(minutes=1),
            )
        )
    )

    with pytest.raises(SampleSourcePolicyError) as captured:
        asyncio.run(_require(policy))

    assert captured.value.code == "official_api_reconciled"


def test_refundable_capture_is_not_blocked_by_free_official_scope():
    policy = SampleSourcePolicy(
        Repository(
            SampleShopAccess(
                "platform-1",
                frozenset({SAMPLE_APPLICATION_SCOPE}),
            )
        )
    )
    asyncio.run(
        policy.require_hubstudio_fallback(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            platform_shop_id="platform-1",
            official_access_state="missing_scope",
            sample_type="refundable",
        )
    )


def test_refundable_still_requires_exact_authorized_shop():
    policy = SampleSourcePolicy(Repository(SampleShopAccess("platform-2", frozenset())))
    with pytest.raises(SampleSourcePolicyError) as captured:
        asyncio.run(
            policy.require_hubstudio_fallback(
                tenant_id=uuid4(),
                shop_id=uuid4(),
                platform_shop_id="platform-1",
                official_access_state="missing_scope",
                sample_type="refundable",
            )
        )
    assert captured.value.code == "platform_shop_mismatch"
