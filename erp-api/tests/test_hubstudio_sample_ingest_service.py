from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.services.hubstudio_sample_network_listener import (
    HubStudioSampleCapture,
)
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSampleTarget,
)
from erp_api.services.hubstudio_sample_ingest_service import (
    HubStudioSampleIngestService,
)
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)


class FakeAudits:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.batch_id = uuid4()
        self.run_id = uuid4()
        self.started: list[dict[str, object]] = []
        self.finished: list[dict[str, object]] = []

    async def start(self, **kwargs):
        self.events.append("batch_started")
        self.started.append(kwargs)
        return self.batch_id, self.run_id

    async def finish(self, **kwargs):
        self.events.append("batch_finished")
        self.finished.append(kwargs)


class FakeApplications:
    def __init__(
        self, events: list[str], *, fail: bool = False, changed: bool = True
    ) -> None:
        self.events = events
        self.fail = fail
        self.changed = changed
        self.calls: list[dict[str, object]] = []

    async def upsert_source_payloads(self, **kwargs):
        self.events.append("application_batch_upserted")
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("database unavailable")
        return tuple(uuid4() for _ in kwargs["observations"])

    async def list_source_changed_since(self, **kwargs):
        return tuple(kwargs["application_ids"]) if self.changed else ()


def _target() -> HubStudioSampleTarget:
    return HubStudioSampleTarget(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        environment_id="1809223023",
        platform_shop_id="platform-1",
        cdp_url="http://127.0.0.1:55111",
        official_access_state="missing_scope",
    )


def _capture(
    target: HubStudioSampleTarget,
    application_id: str,
    *,
    next_token: str | None,
    total: int | None,
    request_id: str,
) -> HubStudioSampleCapture:
    return HubStudioSampleCapture(
        target=target,
        observed_at=datetime(2026, 10, 8, 2, 0, tzinfo=UTC),
        page=TikTokSampleApplicationPage(
            applications=(
                {
                    "id": application_id,
                    "status": "PENDING",
                    "creator": {"id": f"creator-{application_id}"},
                    "product": {"id": f"product-{application_id}"},
                    "token": "must-not-persist",
                },
            ),
            next_page_token=next_token,
            total_count=total,
            platform_request_id=request_id,
        ),
    )


def test_ingest_starts_batch_before_upsert_and_finishes_terminal_pagination() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events)
    service = HubStudioSampleIngestService(audits, applications)
    target = _target()

    first = asyncio.run(
        service.ingest_page(
            _capture(target, "sample-1", next_token="next-1", total=2, request_id="r1")
        )
    )
    second = asyncio.run(
        service.ingest_page(
            _capture(target, "sample-2", next_token=None, total=2, request_id="r2")
        )
    )

    assert first.status == "running"
    assert first.application_ids == ()
    assert second.status == "succeeded"
    assert len(second.application_ids) == 2
    assert second.changed_application_ids == second.application_ids
    assert events == [
        "batch_started",
        "application_batch_upserted",
        "batch_finished",
    ]
    assert audits.started[0]["source_type"] == "hubstudio_cdp"
    assert audits.started[0]["sync_type"] == "source_to_postgres"
    assert len(audits.finished) == 1
    finished = audits.finished[0]
    assert finished["status"] == "succeeded"
    assert finished["page_count"] == 2
    assert finished["captured_total"] == 2
    assert finished["request_ids"] == ["r1", "r2"]
    assert finished["evidence"]["pagination_complete"] is True  # type: ignore[index]
    assert len(applications.calls) == 1
    assert applications.calls[0]["source_type"] == "hubstudio_cdp"
    observations = applications.calls[0]["observations"]
    assert len(observations) == 2
    assert all(item.source_capture_id == audits.batch_id for item in observations)
    assert all(
        item.observed_at == datetime(2026, 10, 8, 2, 0, tzinfo=UTC)
        for item in observations
    )
    assert "token" not in observations[0].payload


def test_unchanged_latest_window_is_exposed_to_local_work_gate() -> None:
    events: list[str] = []
    service = HubStudioSampleIngestService(
        FakeAudits(events),
        FakeApplications(events, changed=False),
        latest_window=True,
    )

    result = asyncio.run(
        service.ingest_page(
            _capture(
                _target(),
                "sample-1",
                next_token="next-page",
                total=None,
                request_id="r1",
            )
        )
    )

    assert len(result.application_ids) == 1
    assert result.changed_application_ids == ()


def test_ingest_reports_group_children_for_feishu_cleanup() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events)
    service = HubStudioSampleIngestService(audits, applications)
    target = _target()
    capture = _capture(
        target,
        "parent",
        next_token=None,
        total=1,
        request_id="r1",
    )
    capture.page.applications[0]["source_item_ids"] = [
        "parent",
        "child-1",
        "child-2",
    ]
    capture.page.applications[0]["products"] = []

    result = asyncio.run(service.ingest_page(capture))

    assert result.obsolete_platform_application_ids == frozenset(
        {"child-1", "child-2"}
    )


def test_terminal_count_mismatch_finishes_partial() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events)
    service = HubStudioSampleIngestService(audits, applications)
    target = _target()

    result = asyncio.run(
        service.ingest_page(
            _capture(target, "sample-1", next_token=None, total=2, request_id="r1")
        )
    )

    assert result.status == "partial"
    assert audits.finished[0]["status"] == "partial"
    assert audits.finished[0]["error_code"] == "total_count_mismatch"
    assert applications.calls == []


def test_latest_window_commits_first_page_with_incomplete_pagination_evidence() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events)
    service = HubStudioSampleIngestService(
        audits, applications, latest_window=True
    )

    result = asyncio.run(
        service.ingest_page(
            _capture(
                _target(),
                "sample-1",
                next_token="next-page",
                total=None,
                request_id="r1",
            )
        )
    )

    assert result.status == "succeeded"
    assert result.page_count == 1
    assert len(applications.calls) == 1
    evidence = audits.finished[0]["evidence"]
    assert evidence["capture_mode"] == "latest_window"  # type: ignore[index]
    assert evidence["pagination_complete"] is False  # type: ignore[index]


def test_ingest_filters_repeated_application_id_before_database_and_feishu_sync() -> None:
    events, target = [], _target()
    applications, audits = FakeApplications(events), FakeAudits(events)
    service = HubStudioSampleIngestService(audits, applications)
    async def run():
        await service.ingest_page(_capture(target, "sample-1", next_token="next", total=1, request_id="r1"))
        later = _capture(target, "sample-1", next_token=None, total=1, request_id="r2")
        return await service.ingest_page(
            replace(later, observed_at=later.observed_at + timedelta(minutes=1))
        )
    assert asyncio.run(run()).status == "succeeded"
    observations = applications.calls[0]["observations"]
    assert [item.payload["id"] for item in observations] == ["sample-1"]
    assert observations[0].observed_at == datetime(2026, 10, 8, 2, 0, tzinfo=UTC)
    assert (audits.finished[0]["captured_total"], audits.finished[0]["evidence"]["duplicates_filtered"]) == (1, 1)


def test_page_window_commits_at_explicit_limit_with_incomplete_evidence() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events)
    service = HubStudioSampleIngestService(audits, applications, page_limit=2)
    target = _target()

    first = asyncio.run(
        service.ingest_page(
            _capture(target, "sample-1", next_token="next-1", total=None, request_id="r1")
        )
    )
    second = asyncio.run(
        service.ingest_page(
            _capture(target, "sample-2", next_token="next-2", total=None, request_id="r2")
        )
    )

    assert first.status == "running"
    assert second.status == "succeeded"
    evidence = audits.finished[0]["evidence"]
    assert evidence["capture_mode"] == "page_window"  # type: ignore[index]
    assert evidence["page_limit"] == 2  # type: ignore[index]
    assert evidence["page_limit_reached"] is True  # type: ignore[index]
    assert evidence["pagination_complete"] is False  # type: ignore[index]


def test_upsert_failure_finishes_existing_batch_before_raising() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events, fail=True)
    service = HubStudioSampleIngestService(audits, applications)

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(
            service.ingest_page(
                _capture(
                    _target(),
                    "sample-1",
                    next_token=None,
                    total=1,
                    request_id="r1",
                )
            )
        )

    assert events == [
        "batch_started",
        "application_batch_upserted",
        "batch_finished",
    ]
    assert audits.finished[0]["status"] == "failed"
    assert audits.finished[0]["error_summary"] == (
        "HubStudio sample application ingest did not complete."
    )


def test_abort_finishes_only_the_named_shop_batch() -> None:
    events: list[str] = []
    audits = FakeAudits(events)
    applications = FakeApplications(events)
    service = HubStudioSampleIngestService(audits, applications)
    first_target = _target()
    second_target = _target()

    async def run() -> None:
        await service.ingest_page(
            _capture(
                first_target,
                "first-1",
                next_token="next",
                total=2,
                request_id="first-r1",
            )
        )
        await service.ingest_page(
            _capture(
                second_target,
                "second-1",
                next_token="next",
                total=2,
                request_id="second-r1",
            )
        )
        assert await service.abort(first_target, "session_expired") is True
        result = await service.ingest_page(
            _capture(
                second_target,
                "second-2",
                next_token=None,
                total=2,
                request_id="second-r2",
            )
        )
        assert result.status == "succeeded"

    asyncio.run(run())

    assert audits.finished[0]["shop_id"] == first_target.shop_id
    assert audits.finished[0]["status"] == "partial"
    assert audits.finished[0]["error_code"] == "session_expired"
    assert audits.finished[1]["shop_id"] == second_target.shop_id
    assert audits.finished[1]["status"] == "succeeded"
    assert len(applications.calls) == 1
    assert applications.calls[0]["shop_id"] == second_target.shop_id
