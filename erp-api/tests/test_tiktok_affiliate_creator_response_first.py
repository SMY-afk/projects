"""A verified TikTok file response must not depend on CDP download events."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.services.tiktok_affiliate_creator_export_download import (
    download_creator_export,
)

FILE_ID = "verified-file-id-12345"
CONTENT = b"PK\x03\x04original-xlsx"


class FakeResponse:
    def __init__(self, url: str, *, export: bool = False):
        self.url = url
        self.status = 200
        self.export = export

    async def header_value(self, name):
        return "application/json" if name == "content-type" and self.export else None

    async def json(self):
        return {"code": 0, "data": {"file": FILE_ID}}

    async def body(self):
        return CONTENT


class FakeExpectResponse:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    @property
    def value(self):
        async def result():
            return self.response

        return result()


class FakeButton:
    async def wait_for(self, **_):
        return None

    async def click(self):
        return None


class FakePage:
    def __init__(self):
        host = "https://affiliate.tiktokshopglobalselling.com"
        self.responses = iter((
            FakeResponse(host + "/api/v3/insights/affiliate/seller/creator/filter_list/export", export=True),
            FakeResponse(host + "/api/v1/insights/export/file/" + FILE_ID),
        ))

    def locator(self, _):
        return SimpleNamespace(last=FakeButton())

    def expect_response(self, *_args, **_kwargs):
        return FakeExpectResponse(next(self.responses))

    def expect_download(self, **_):
        pytest.fail("A verified file response must not wait for a CDP download")

    def on(self, event, callback):
        assert event == "download"
        self.download_callback = callback

    def remove_listener(self, event, callback):
        assert event == "download"
        assert callback is self.download_callback


@pytest.mark.asyncio
async def test_verified_file_response_completes_without_download_event():
    content, file_id, download, request_id = await asyncio.wait_for(
        download_creator_export(FakePage()), timeout=0.5
    )
    assert (content, file_id, download, request_id) == (CONTENT, FILE_ID, None, None)
