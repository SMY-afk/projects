import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.parsers.affiliate_video_export_parser import AffiliateVideoExportParseError
from backend.app.services import tiktok_affiliate_export_intent as export_intent
from backend.app.services.tiktok_affiliate_video_export_sync import (
    _parse_failure_event,
)


class _Prepared:
    def __init__(self) -> None:
        self.cleaned = False

    async def cleanup(self) -> None:
        self.cleaned = True


class _Repository:
    def __init__(self) -> None:
        self.failures = []

    async def fail_intent(self, tenant_id, run_id, category) -> None:
        self.failures.append((tenant_id, run_id, category))


def test_unexpected_video_export_error_finishes_the_running_intent(monkeypatch) -> None:
    async def fail_export(prepared, capture) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(export_intent, "sync_video_export", fail_export)
    prepared = _Prepared()
    repository = _Repository()
    tenant_id = uuid4()
    run_id = uuid4()
    intent = SimpleNamespace(
        resource="videos",
        run_id=run_id,
        shop_id=uuid4(),
    )

    handled = asyncio.run(
        export_intent.run_export_intent(
            prepared,
            object(),
            object(),
            repository,
            tenant_id,
            intent,
            None,
            asyncio.Event(),
        )
    )

    assert handled is True
    assert repository.failures == [
        (tenant_id, run_id, "video_export_persistence_failed")
    ]
    assert prepared.cleaned is True


def test_us_video_intent_skips_the_sparse_excel_export(monkeypatch) -> None:
    async def unexpected_export(prepared, capture) -> None:
        raise AssertionError("US video capture must use the page data API")

    monkeypatch.setattr(export_intent, "sync_video_export", unexpected_export)
    prepared = SimpleNamespace(
        page=SimpleNamespace(
            url="https://affiliate-us.tiktok.com/affiliate/assets/video-analysis"
        )
    )

    handled = asyncio.run(
        export_intent.run_export_intent(
            prepared,
            object(),
            object(),
            _Repository(),
            uuid4(),
            SimpleNamespace(resource="videos", run_id=uuid4(), shop_id=uuid4()),
            None,
            asyncio.Event(),
        )
    )

    assert handled is False


def test_video_parser_failure_log_contains_only_a_fixed_field_and_reason() -> None:
    event = _parse_failure_event(
        AffiliateVideoExportParseError("Row 3 视频播放量 is not numeric")
    )

    assert event == "affiliate_video_export_parse_failed_views_invalid_number"


def test_root_error_code_redacts_metric_values() -> None:
    root = ValueError("ratio must be between 0 and 1")
    field_error = ValueError("finishRate: ratio must be between 0 and 1: 1.2345")
    field_error.__cause__ = root
    wrapped = RuntimeError("Video export persistence failed")
    wrapped.__cause__ = field_error

    assert export_intent._root_error_code(wrapped) == "finish_rate_ratio_above_one"
