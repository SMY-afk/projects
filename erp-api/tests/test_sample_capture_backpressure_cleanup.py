"""A stopped consumer must release response tasks blocked by a full queue."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.services import hubstudio_raw_sample_capture as capture


@pytest.mark.asyncio
async def test_full_response_queue_does_not_block_failed_capture_cleanup(monkeypatch):
    class Store:
        def recover_completed(self):
            return None

        def abandon_capturing(self, _):
            return 0

        def start_batch(self):
            return 1

    class Page:
        def on(self, _, callback):
            self.callback = callback

        def remove_listener(self, *_):
            pass

    page = Page()

    async def load(*_):
        response = SimpleNamespace(
            url="https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/group/list",
            request=SimpleNamespace(method="POST", post_data='{"tab":10,"order_params":[],"search_params":[]}'),
        )
        for _ in range(20):
            page.callback(response)
        await asyncio.sleep(0)

    async def read(*args):
        await args[-2].put(RuntimeError("source_gap"))

    monkeypatch.setattr(capture, "_load_first_page", load)
    monkeypatch.setattr(capture, "_read_response", read)
    with pytest.raises(RuntimeError, match="source_gap"):
        await asyncio.wait_for(
            capture.capture_review_batch_from_page(page, "shop", Store()), 0.3
        )
