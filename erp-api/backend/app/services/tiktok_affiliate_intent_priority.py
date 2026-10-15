from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from uuid import UUID

from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntent,
    AffiliateCaptureIntentRepository,
)

RUN_TIMEOUT_SECONDS = 930.0
CREATOR_RUN_TIMEOUT_SECONDS = 1830.0
VIDEO_RUN_TIMEOUT_SECONDS = 1830.0


def detail_backfill_enabled() -> bool:
    value = os.getenv("AFFILIATE_DETAIL_BACKFILL_ENABLED", "1")
    return value.strip().casefold() not in {"0", "false", "no", "off"}


def intent_timeout_seconds(resource: str) -> float:
    if resource == "creators":
        return CREATOR_RUN_TIMEOUT_SECONDS
    if resource == "videos":
        return VIDEO_RUN_TIMEOUT_SECONDS
    return RUN_TIMEOUT_SECONDS


_POLL_INTERVAL_SECONDS = 2.0


async def wait_for_intent(
    repository: AffiliateCaptureIntentRepository,
    tenant_id: UUID,
    stopped: asyncio.Event,
    *,
    platform_shop_ids: frozenset[str],
    preempt_tasks: Iterable[asyncio.Task[None]] = (),
) -> AffiliateCaptureIntent | None:
    while not stopped.is_set():
        intent = await repository.next_queued(tenant_id, platform_shop_ids)
        if intent is not None:
            await _stop_background_tasks(preempt_tasks)
            return intent
        try:
            await asyncio.wait_for(stopped.wait(), timeout=_POLL_INTERVAL_SECONDS)
        except TimeoutError:
            pass
    return None


async def wait_for_completion(
    done: asyncio.Event,
    stopped: asyncio.Event,
    *,
    timeout_seconds: float,
) -> None:
    done_task = asyncio.create_task(done.wait())
    stopped_task = asyncio.create_task(stopped.wait())
    try:
        await asyncio.wait_for(
            asyncio.wait(
                (done_task, stopped_task),
                return_when=asyncio.FIRST_COMPLETED,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return
    finally:
        for task in (done_task, stopped_task):
            task.cancel()


async def _stop_background_tasks(tasks: Iterable[asyncio.Task[None]]) -> None:
    pending = list(tasks)
    for task in pending:
        if not task.done():
            task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
