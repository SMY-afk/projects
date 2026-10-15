from unittest.mock import AsyncMock

import pytest

from backend.app.services import hubstudio_raw_sample_capture as capture
from backend.app.services import sample_review_page_refresh as refresh
from backend.app.services.sample_persistent_target import persistent_sample_key


@pytest.mark.asyncio
@pytest.mark.parametrize("shop_id", [
    "9622543325839925006", "9768147009521852682", "9472478445887813622",
])
async def test_free_capture_resets_sticky_refundable_tab(monkeypatch, shop_id):
    page = AsyncMock()
    prepare = AsyncMock()
    monkeypatch.setattr(refresh, "prepare_sample_review_page", prepare)

    await capture._load_first_page(page, shop_id, "https://example.com")

    prepare.assert_awaited_once_with(page, select_free=True)


def test_cross4_reuses_one_approved_page_for_both_sample_types():
    platform_id = "9768147009521852682"
    assert persistent_sample_key(platform_id, "free") == (platform_id, "free")
    assert persistent_sample_key(platform_id, "refundable") == (platform_id, "free")
