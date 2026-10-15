"""Only the verified live Ziniao browser may supply fallback XLSX files."""

import asyncio
from types import SimpleNamespace

import pytest

from scripts import ziniao_affiliate_export_source as source


def test_download_dir_matches_current_browser_identity(monkeypatch, tmp_path):
    directory = tmp_path / "shop-A"
    directory.mkdir()
    settings = SimpleNamespace(ziniao_akeleo_browser_name="shop-A")

    async def running(_settings):
        return {"debuggingPort": 12345, "downloadPath": str(directory)}

    monkeypatch.setattr(source, "get_settings", lambda: settings)
    monkeypatch.setattr(source, "_running_browser", running)

    assert asyncio.run(source.verified_ziniao_download_dir("http://127.0.0.1:12345")) == directory
    with pytest.raises(RuntimeError, match="differs"):
        asyncio.run(source.verified_ziniao_download_dir("http://127.0.0.1:54321"))
