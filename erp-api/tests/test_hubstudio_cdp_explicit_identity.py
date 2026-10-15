"""Explicit target identities must not depend on unrelated seller renderers."""

import asyncio

from backend.app.services.hubstudio_cdp import read_cdp_platform_shop_ids


def test_explicit_shop_identity_skips_unresponsive_seller_storage(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return [
                {"type": "page", "url": "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=9121478993551097445"},
                {"type": "page", "url": "https://seller.tiktokshopglobalselling.com/affiliate/landing"},
            ]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, _):
            return Response()

    async def storage_reader(_):
        raise AssertionError("Explicit shop URL already establishes identity")

    monkeypatch.setattr(
        "backend.app.services.hubstudio_cdp.httpx.AsyncClient", lambda **_: Client()
    )
    monkeypatch.setattr(
        "backend.app.services.hubstudio_cdp._read_seller_storage_shop_ids",
        storage_reader,
    )
    assert asyncio.run(read_cdp_platform_shop_ids("http://127.0.0.1:62968")) == (
        frozenset({"9121478993551097445"})
    )
