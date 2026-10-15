"""Persisted legacy final-page batches must not bypass the new start gate."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.app.services import sample_raw_capture_retry as retry
from scripts import send_local_sample_capture as delivery


def _stored(tmp_path, first_page):
    batch = SimpleNamespace(sequence=1, path=tmp_path, page_count=1, expected_total=0, captured_total=0)
    page = SimpleNamespace(
        request_page=first_page, request_cursor=f'[["cur_page",{first_page}]]', request_id="r1",
        response_observed_at=datetime.now(UTC), response_has_more=False, response_total_count=0,
        payload={"agg_info": [], "has_more": False, "total_count": 0},
    )
    store = SimpleNamespace(recover_completed=lambda: batch, load_pages=lambda _batch: [page],
                            supersede_completed=Mock())
    return batch, store


def test_legacy_final_page_batch_is_retained_but_cannot_resume(tmp_path):
    batch, store = _stored(tmp_path, 8)
    assert retry.recover_fresh_completed(store) is None
    store.supersede_completed.assert_called_once_with(batch, reason="invalid_pagination")


def test_verified_first_page_batch_still_resumes(tmp_path):
    batch, store = _stored(tmp_path, 1)
    assert retry.recover_fresh_completed(store) is batch
    store.supersede_completed.assert_not_called()


@pytest.mark.asyncio
async def test_final_page_only_batch_cannot_read_token_or_upload(tmp_path):
    _batch, store = _stored(tmp_path, 8)
    token_file = SimpleNamespace(read_text=Mock(side_effect=AssertionError("Token must not be read")))
    args = SimpleNamespace(raw_store=store, verify_batch_sequence=None, capture=False, shop_id=uuid4(),
                           sample_type="free", environment_id="802623795", platform_shop_id="9622543325839925006",
                           token_file=token_file)
    with pytest.raises(RuntimeError, match="first page"):
        await delivery.run(args)
    token_file.read_text.assert_not_called()
