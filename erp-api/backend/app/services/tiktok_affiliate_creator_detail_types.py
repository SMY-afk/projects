from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from uuid import UUID

from playwright.async_api import Page


class CreatorDetailCaptureError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass
class ActiveCreatorDetail:
    report_id: UUID
    run_id: UUID
    page: Page
    query_key: tuple[object, ...]
    seen_pages: set[int] = field(default_factory=set)
    empty_pages: int = 0
    started_at: float = field(default_factory=monotonic)


def track_creator_detail_task(
    tasks: set[asyncio.Task[None]], task: asyncio.Task[None]
) -> None:
    tasks.add(task)

    def done(completed: asyncio.Task[None]) -> None:
        tasks.discard(completed)
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(done)
