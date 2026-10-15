import asyncio
from datetime import date

from backend.app.services.tiktok_affiliate_video_export_download import _select_date


def test_calendar_waits_for_panels_before_reading_months():
    clicked = []

    class Cell:
        async def inner_text(self):
            return "6"

        async def click(self):
            clicked.append(True)

    class Cells:
        async def count(self):
            return 1

        def nth(self, index):
            return Cell()

    class Header:
        async def inner_text(self):
            return "2026-10"

    class Panel:
        def locator(self, selector):
            return Header() if selector == ".core-picker-header-value" else Cells()

    class Panels:
        ready = False

        async def count(self):
            return int(self.ready)

        @property
        def first(self):
            return self

        async def wait_for(self, **options):
            assert options["state"] == "visible"
            self.ready = True

        def nth(self, index):
            return Panel()

    class Trigger:
        panels = Panels()

        def locator(self, selector):
            return self.panels

    asyncio.run(_select_date(Trigger(), date(2026, 10, 6)))
    assert clicked == [True]
