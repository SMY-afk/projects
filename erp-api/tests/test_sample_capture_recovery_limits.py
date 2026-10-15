import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.app.services import sample_raw_owned_page as owned
from scripts.run_refundable_sample_capture_loop import terminal_recent


def test_eight_existing_tabs_prevent_ninth_owned_target(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "type": "page",
                    "id": str(n),
                    "url": (
                        "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
                        "sample-request?shop_id=shop-7&shop_region=US"
                    ),
                }
                for n in range(8)
            ]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, _url):
            return Response()

    monkeypatch.setattr(owned.httpx, "AsyncClient", lambda **_kwargs: Client())

    async def check():
        with pytest.raises(RuntimeError, match="tab_limit_reached"):
            async with owned.open_owned_sample_page(None, "endpoint", "shop-7"):
                pytest.fail("Browser tab limit bypassed")

    asyncio.run(check())


def test_terminal_paid_tabs_wait_thirty_minutes(tmp_path):
    args = SimpleNamespace(status_dir=tmp_path, shop_label="cross-border-7")
    path = tmp_path / "cross-border-7-4.status.json"
    path.write_text(
        json.dumps({"at": datetime.now(UTC).isoformat(), "state": "stored"})
    )
    assert terminal_recent(args, 4)
    assert not terminal_recent(args, 5)
