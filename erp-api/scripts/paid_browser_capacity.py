"""Wait briefly for existing slots; free-priority cancellation stays external."""

import asyncio
from contextlib import AsyncExitStack
from time import monotonic

from scripts.local_capture_guard import CaptureGuardError, browser_work


async def wait_for_browser_capacity(label, operation, *, timeout=45, guard=None, can_wait=None):
    deadline = monotonic() + timeout
    guard = guard or browser_work
    while True:
        if can_wait is not None and not can_wait():
            raise CaptureGuardError("free_priority_wait")
        async with AsyncExitStack() as stack:
            try:
                stack.enter_context(guard(label))
            except CaptureGuardError as error:
                if error.code not in {"browser_busy", "capture_capacity_busy"}:
                    raise
                if monotonic() >= deadline:
                    raise
            else:
                return await operation()
        # This is a local lock wait, not a browser request or a page refresh.
        await asyncio.sleep(0.5)
