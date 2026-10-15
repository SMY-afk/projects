"""Wait on local evidence only; never navigate or manufacture a free window."""

import asyncio
from time import monotonic

from scripts.sample_capture_priority import secondary_budget


async def wait_for_free_window(label, timeout, *, root=None):
    deadline = monotonic() + max(0, timeout)
    options = {} if root is None else {"root": root}
    while True:
        if secondary_budget(label, **options) > 0:
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(2, remaining))
