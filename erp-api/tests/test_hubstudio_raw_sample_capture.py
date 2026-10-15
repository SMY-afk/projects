from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.services import sample_raw_capture_retry as retry_module
from backend.app.services.hubstudio_raw_sample_capture import (
    is_review_request_date,
)
from backend.app.services.sample_owned_page_url import build_owned_sample_url
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_capture_metadata import parse_request_marker
from backend.app.services.sample_raw_owned_page import is_expected_browser_shop

OBSERVED_AT = datetime(2026, 10, 8, 8, tzinfo=UTC)


def test_owned_sample_url_preserves_authenticated_shop_region() -> None:
    targets = [{
        "id": "target-1",
        "type": "page",
        "url": (
            "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
            "sample-request?shop_region=US&shop_id=123"
        ),
    }]

    assert build_owned_sample_url(
        targets,
        "123",
        host="affiliate.tiktokshopglobalselling.com",
        path="/affiliate/sample/sample-request",
    ) == (
        "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/"
        "sample-request?shop_region=US&shop_id=123"
    )


def test_expected_browser_shop_rejects_mixed_shops() -> None:
    targets = [
        {"type": "page", "url": "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=123"},
        {"type": "page", "url": "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis?shop_id=456"},
    ]
    assert not is_expected_browser_shop(targets, "123")


def test_review_request_date_rejects_all_status_and_other_hosts() -> None:
    body = (
        '{"tab":10,"order_params":[],'
        '"search_params":[]}'
    )
    assert is_review_request_date(
        "https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/group/list",
        "POST", body,
    )
    assert not is_review_request_date(
        "https://example.com/api/v1/affiliate/sample/group/list", "POST", body,
    )
    assert not is_review_request_date(
        "https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/group/list",
        "POST", '{"tab":0,"order_params":[],"search_params":[]}',
    )
    assert not is_review_request_date(
        "https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/group/list",
        "POST",
        '{"tab":10,"order_params":[{"order_key":7,"order_type":2}],'
        '"search_params":[]}',
    )


def test_cross12_raw_launcher_uses_one_minute_review_cycles() -> None:
    source = Path("scripts/start-cross12-raw-sample-watch.ps1").read_text(
        encoding="utf-8"
    )

    assert "param([double]$IntervalSeconds = 60)" in source


@pytest.mark.asyncio
async def test_raw_watch_retries_transient_request_date_control(monkeypatch) -> None:
    calls = []
    expected = object()

    class Store:
        def abandon_capturing(self, reason: str) -> int:
            calls.append(("abandon", reason))
            return 1

    async def capture(*_args, **_kwargs):
        calls.append("capture")
        if len(calls) == 1:
            raise RuntimeError("sample_request_date_sort_unavailable")
        return expected

    async def sleep(seconds):
        calls.append(("sleep", seconds))

    async def security_state(_endpoint):
        return "online"

    monkeypatch.setattr(retry_module, "capture_review_batch", capture)
    monkeypatch.setattr(retry_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(retry_module, "browser_security_state", security_state)

    result = await retry_module.capture_review_batch_with_retry(
        "http://127.0.0.1:1234", "shop", Store(), timeout_seconds=30
    )

    assert result is expected
    assert calls == [
        "capture",
        ("abandon", "incomplete_batch_retry"),
        ("sleep", 30),
        "capture",
    ]


def test_raw_batch_store_persists_sequence_and_recovers_completed_batch(
    tmp_path: Path,
) -> None:
    store = SampleRawBatchStore(tmp_path, "shop-123")
    first = store.start_batch()
    store.persist_page(
        first,
        1,
        {"data": {"groups": []}},
        request_id="request-1",
        request_page=1,
        request_cursor='[["cur_page",1]]',
        response_has_more=False,
        response_total_count=0,
        response_observed_at=OBSERVED_AT,
    )
    store.complete_batch(
        first,
        1,
        expected_total=0,
        captured_total=0,
        terminal_confirmed=True,
    )

    restarted = SampleRawBatchStore(tmp_path, "shop-123")
    recovered = restarted.recover_completed()

    assert first == 1
    assert recovered is not None
    assert recovered.sequence == 1
    assert recovered.expected_total == 0
    page = restarted.load_pages(recovered)[0]
    assert (page.request_id, page.request_cursor) == ("request-1", '[["cur_page",1]]')
    assert page.response_observed_at == OBSERVED_AT
    envelope = next((tmp_path / "shop-123").glob("batch-*/page-*.json"))
    assert '"page":1' in envelope.read_text(encoding="utf-8")
    restarted.acknowledge(recovered)
    assert restarted.recover_completed() is None
    assert restarted.start_batch() == 2


def test_raw_batch_store_keeps_group_reported_total_as_audit_only(
    tmp_path: Path,
) -> None:
    store = SampleRawBatchStore(tmp_path, "shop-123")
    sequence = store.start_batch()
    store.persist_page(
        sequence,
        1,
        {"agg_info": []},
        request_id="request-1",
        request_page=1,
        request_cursor='[["cur_page",1]]',
        response_has_more=False,
        response_total_count=4,
        response_observed_at=OBSERVED_AT,
    )

    store.complete_batch(
        sequence,
        1,
        expected_total=None,
        captured_total=0,
        terminal_confirmed=True,
    )

    manifest = next((tmp_path / "shop-123").glob("batch-*/manifest.json"))
    assert '"expected_total":null' in manifest.read_text(encoding="utf-8")
    assert '"reported_total_count":4' in manifest.read_text(encoding="utf-8")


def test_raw_request_marker_reads_nested_page_and_cursor() -> None:
    marker = parse_request_marker(
        '{"tab":10,"pagination":{"page_num":3,"cursor":"next-3"}}',
        fallback_page=99,
    )

    assert marker.page == 3
    assert "pagination.page_num" in marker.cursor
    assert "pagination.cursor" in marker.cursor


def test_raw_request_marker_reads_live_group_list_cur_page() -> None:
    marker = parse_request_marker(
        '{"tab":10,"cur_page":7,"page_size":50}', fallback_page=99
    )

    assert marker.page == 7
    assert "cur_page" in marker.cursor


def test_raw_batch_store_never_recovers_incomplete_batch(tmp_path: Path) -> None:
    store = SampleRawBatchStore(tmp_path, "shop-123")
    sequence = store.start_batch()
    store.persist_page(
        sequence,
        1,
        {"data": {"groups": []}},
        request_id="request-1",
        request_page=1,
        request_cursor='[["cur_page",1]]',
        response_has_more=False,
        response_total_count=0,
        response_observed_at=OBSERVED_AT,
    )

    assert SampleRawBatchStore(tmp_path, "shop-123").recover_completed() is None


def test_raw_batch_store_rejects_duplicate_cursor_and_missing_terminal(
    tmp_path: Path,
) -> None:
    store = SampleRawBatchStore(tmp_path, "shop-123")
    sequence = store.start_batch()
    for page_sequence, has_more in ((1, True), (2, False)):
        store.persist_page(
            sequence,
            page_sequence,
            {"data": {"groups": []}},
            request_id=f"request-{page_sequence}",
            request_page=page_sequence,
            request_cursor="duplicate-cursor",
            response_has_more=has_more,
            response_total_count=0,
            response_observed_at=OBSERVED_AT,
        )

    with pytest.raises(RuntimeError, match="cursor"):
        store.complete_batch(
            sequence,
            2,
            expected_total=0,
            captured_total=0,
            terminal_confirmed=True,
        )


def test_raw_capture_never_closes_externally_owned_browser() -> None:
    source = Path(
        "backend/app/services/hubstudio_raw_sample_capture.py"
    ).read_text(encoding="utf-8")
    owned_page = Path("backend/app/services/sample_raw_owned_page.py").read_text(
        encoding="utf-8"
    )
    page_controls = Path(
        "backend/app/services/sample_request_page_controls.py"
    ).read_text(encoding="utf-8")

    assert "await browser.close()" not in source + owned_page
    assert "connect_attached_hubstudio_browser" in owned_page
    assert "open_owned_sample_page" in source
    assert "await response.finished()" not in source
    assert "await response.finished()" not in page_controls
    assert "captured_page.next_page_token is None" in source


def test_cross_border_launchers_use_raw_queue_for_every_cross_border_shop() -> None:
    launcher = Path("scripts/start-hubstudio-sample-watches.ps1").read_text(
        encoding="utf-8"
    )
    runner = Path("scripts/run_hubstudio_raw_sample_watch.py").read_text(
        encoding="utf-8"
    )
    guardian = Path("scripts/sample-watch-guardian.ps1").read_text(
        encoding="utf-8"
    )

    assert '"-u", "-m", "scripts.run_hubstudio_raw_sample_watch"' in launcher
    assert "[double]$ProcessingTimeoutSeconds = 1800" in launcher
    assert '"--processing-timeout-seconds", type=float, default=1800' in runner
    assert "-ProcessingTimeoutSeconds 1800" in guardian
    for shop in ("cross-border-3", "cross-border-4", "cross-border-7"):
        target_line = next(
            line for line in guardian.splitlines() if f'Name = "{shop}"' in line
        )
        assert 'Module = "scripts.run_hubstudio_raw_sample_watch"' in target_line


def test_raw_batch_is_acknowledged_before_downstream_business_processing() -> None:
    runner = Path("scripts/run_hubstudio_raw_sample_watch.py").read_text(
        encoding="utf-8"
    )

    acknowledge = runner.index("raw_store.acknowledge")
    downstream = runner.index("pipeline.complete_after_source")

    assert acknowledge < downstream
