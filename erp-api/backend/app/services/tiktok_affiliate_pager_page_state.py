import asyncio
from dataclasses import dataclass, field

from playwright.async_api import Page


@dataclass
class PageState:
    page: Page
    resource: str
    selector: str
    active_task: asyncio.Task[None] | None = None
    page_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
