"""Busy captures remain pending; obsolete captures remain archived on disk."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from scripts.send_local_sample_capture import (
    CaptureIngressError,
    reject_ingress_response,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("detail,code", [
    ("Shop sample sync is busy", "busy"),
    ("RAW sample batch is older than stored source", "stale_capture"),
])
async def test_ingress_conflict_preserves_raw_capture(tmp_path, detail, code):
    store = SampleRawBatchStore(tmp_path, "shop")
    sequence = store.start_batch()
    store.persist_page(
        sequence, 1, {"data": {"groups": []}}, request_id="r1", request_page=1,
        request_cursor='[["cur_page",1]]', response_has_more=False, response_total_count=0,
        response_observed_at=datetime.now(UTC),
    )
    batch = store.complete_batch(sequence, 1, expected_total=0, captured_total=0, terminal_confirmed=True)
    response = SimpleNamespace(status_code=409, headers={"x-erp-capture-error": code})
    with pytest.raises(CaptureIngressError) as error:
        await reject_ingress_response(response, store, batch)
    assert error.value.code == code
    assert (batch.path / "page-000001.json").is_file()
    assert (store.recover_completed() is not None) == (code == "busy")
