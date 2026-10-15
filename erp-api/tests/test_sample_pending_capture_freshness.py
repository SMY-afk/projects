from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.services import sample_raw_capture_retry as module


@pytest.mark.parametrize("age,keep", [(60, True), (901, False)])
def test_resume_keeps_only_fresh_completed_raw(age, keep):
    now = datetime(2026, 10, 12, 5, 40, tzinfo=UTC)
    batch = SimpleNamespace(expected_total=0, captured_total=0)
    superseded = []
    store = SimpleNamespace(
        recover_completed=lambda: batch,
        load_pages=lambda _batch: [
            SimpleNamespace(response_observed_at=now - timedelta(seconds=age),
                            request_page=1, request_id="r1", request_cursor='[["cur_page",1]]',
                            response_has_more=False, response_total_count=0)
        ],
        supersede_completed=lambda b, **kwargs: superseded.append((b, kwargs)),
    )
    result = module.recover_fresh_completed(store, now=now)
    assert (result is batch) == keep
    assert superseded == ([] if keep else [(batch, {"reason": "capture_expired"})])


def test_future_capture_is_preserved_for_audit_instead_of_uploaded():
    now = datetime(2026, 10, 12, 5, 40, tzinfo=UTC)
    store = SimpleNamespace(
        recover_completed=lambda: object(),
        load_pages=lambda _batch: [
            SimpleNamespace(response_observed_at=now + timedelta(minutes=1))
        ],
    )
    with pytest.raises(RuntimeError, match="sample_capture_clock_invalid"):
        module.recover_fresh_completed(store, now=now)
