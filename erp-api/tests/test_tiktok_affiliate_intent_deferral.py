from __future__ import annotations

import asyncio
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services.tiktok_affiliate_intent_deferral import (
    CaptchaCooldownConfig,
    defer_session_blocked_intent,
    persist_failure_or_deferral,
)


class FakeCaptchaLocator:
    def __init__(self, page) -> None:
        self.page = page

    async def count(self) -> int:
        return 1

    def nth(self, index: int):
        assert index == 0
        return self

    async def is_visible(self) -> bool:
        return self.page.captcha


class FakeCaptchaPage:
    url = "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"

    def __init__(self) -> None:
        self.captcha = True

    def locator(self, selector: str) -> FakeCaptchaLocator:
        assert "captcha" in selector
        return FakeCaptchaLocator(self)


def test_captcha_deferral_waits_for_cooldown_and_stable_manual_recovery() -> None:
    async def run() -> float:
        page = FakeCaptchaPage()
        stopped = asyncio.Event()
        intent = SimpleNamespace(run_id=uuid4(), shop_id=uuid4())

        async def solve() -> None:
            await asyncio.sleep(0.01)
            page.captcha = False

        solved = asyncio.create_task(solve())
        started = monotonic()
        deferred = await defer_session_blocked_intent(
            "captcha",
            uuid4(),
            intent,
            None,
            page=page,
            stopped=stopped,
            cooldown_config=CaptchaCooldownConfig(
                minimum_seconds=0.04,
                poll_seconds=0.005,
                stable_seconds=0.015,
            ),
        )
        await solved
        assert deferred
        return monotonic() - started

    assert asyncio.run(run()) >= 0.035


def test_claimed_captcha_is_requeued_instead_of_failed() -> None:
    class Repository:
        def __init__(self) -> None:
            self.deferred = []
            self.failed = []

        async def defer_intent(self, tenant_id, run_id) -> None:
            self.deferred.append((tenant_id, run_id))

        async def fail_intent(self, tenant_id, run_id, category) -> None:
            self.failed.append((tenant_id, run_id, category))

    async def run():
        repository = Repository()
        tenant_id = uuid4()
        run_id = uuid4()
        blocker = await persist_failure_or_deferral(
            repository,
            tenant_id,
            run_id,
            "captcha",  # type: ignore[arg-type]
        )
        return repository, tenant_id, run_id, blocker

    repository, tenant_id, run_id, blocker = asyncio.run(run())
    assert blocker == "captcha"
    assert repository.deferred == [(tenant_id, run_id)]
    assert repository.failed == []
