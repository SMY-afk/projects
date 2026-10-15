import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services import (
    tiktok_affiliate_creator_export_download as export_download,
)
from backend.app.services import tiktok_affiliate_creator_export_sync as export_sync


class FakeDownload:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def path(self) -> str:
        return str(self._path)

    async def save_as(self, path: str) -> None:
        Path(path).write_bytes(self._path.read_bytes())


class FakeTransientPathDownload(FakeDownload):
    async def save_as(self, path: str) -> None:
        Path(path).write_bytes(b"PK\x03\x04workbook")


class FakeEmptyArtifactDownload(FakeDownload):
    suggested_filename = "Creator_List_20261007-20261008_20261009201251.xlsx"

    async def save_as(self, path: str) -> None:
        Path(path).write_bytes(b"")


class FakeFileResponse:
    url = "https://affiliate.tiktokshopglobalselling.com/api/v1/insights/export/file/valid-id"

    async def body(self) -> bytes:
        return b"PK\x03\x04workbook"


class FakeUnavailableFileResponse(FakeFileResponse):
    async def body(self) -> bytes:
        raise RuntimeError("Response body was navigated away from")


class FakeRequestContext:
    async def get(self, url: str, *, timeout: int, max_redirects: int):
        assert url == FakeFileResponse.url
        assert timeout == 30_000
        assert max_redirects == 0
        return FakeReplayResponse()


class FakeReplayResponse:
    status = 200

    async def body(self) -> bytes:
        return b"PK\x03\x04workbook"

    async def dispose(self) -> None:
        pass


class FakeRequestPage:
    context = SimpleNamespace(request=FakeRequestContext())


class FakeDeleteFailureDownload(FakeDownload):
    async def delete(self) -> None:
        raise RuntimeError("browser cleanup failed")


class FakeExportButton:
    def __init__(self) -> None:
        self.waited = False

    async def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "visible"
        assert timeout == export_download.CREATOR_EXPORT_TIMEOUT_MS
        self.waited = True


class FakeExportLocator:
    def __init__(self, button: FakeExportButton) -> None:
        self.last = button


class FakeExportPage:
    def __init__(self, button: FakeExportButton) -> None:
        self.button = button

    def locator(self, selector: str) -> FakeExportLocator:
        assert selector == export_download.CREATOR_EXPORT_BUTTON
        return FakeExportLocator(self.button)


def test_waits_for_export_button_after_page_range_refresh() -> None:
    button = FakeExportButton()

    resolved = asyncio.run(
        export_download._wait_for_export_button(FakeExportPage(button))
    )

    assert resolved is button
    assert button.waited is True


def test_reads_completed_playwright_download(tmp_path: Path) -> None:
    workbook = tmp_path / "creator-export.bin"
    workbook.write_bytes(b"PK\x03\x04workbook")

    content = asyncio.run(export_download._read_download(FakeDownload(workbook)))

    assert content == b"PK\x03\x04workbook"


def test_reads_download_when_playwright_artifact_path_vanishes(tmp_path: Path) -> None:
    download = FakeTransientPathDownload(tmp_path / "already-gone.xlsx")

    content = asyncio.run(export_download._read_download(download))

    assert content == b"PK\x03\x04workbook"


def test_reads_matching_response_when_download_artifact_is_empty(tmp_path: Path) -> None:
    download = FakeEmptyArtifactDownload(tmp_path / "already-gone.xlsx")

    content = asyncio.run(
        export_download._read_download(download, FakeFileResponse())
    )

    assert content == b"PK\x03\x04workbook"


def test_response_bytes_win_when_attached_browser_download_path_hangs() -> None:
    class HangingDownload:
        async def path(self):
            await asyncio.Future()

    content = asyncio.run(
        asyncio.wait_for(
            export_download._read_download(HangingDownload(), FakeFileResponse()),
            timeout=0.2,
        )
    )
    assert content == b"PK\x03\x04workbook"


def test_verified_replay_wins_when_response_body_and_artifact_are_unavailable() -> None:
    class HangingDownload:
        async def path(self):
            await asyncio.Future()

    content = asyncio.run(
        asyncio.wait_for(
            export_download._read_download(
                HangingDownload(), FakeUnavailableFileResponse(), FakeRequestPage()
            ),
            timeout=0.2,
        )
    )
    assert content == b"PK\x03\x04workbook"


def test_replays_only_verified_file_url_when_response_body_was_lost(tmp_path: Path) -> None:
    download = FakeEmptyArtifactDownload(tmp_path / "already-gone.xlsx")

    content = asyncio.run(
        export_download._read_download(
            download, FakeUnavailableFileResponse(), FakeRequestPage()
        )
    )

    assert content == b"PK\x03\x04workbook"


def test_reads_only_fresh_exact_ziniao_browser_download(tmp_path: Path) -> None:
    download = FakeEmptyArtifactDownload(tmp_path / "missing-artifact")
    original = tmp_path / download.suggested_filename
    original.write_bytes(b"PK\x03\x04workbook")

    content = asyncio.run(
        export_download._read_download(
            download, local_download_dir=tmp_path,
            captured_after=datetime.now(UTC) - timedelta(minutes=1),
        )
    )

    assert content == original.read_bytes()


def test_delete_download_falls_back_to_local_unlink(tmp_path: Path) -> None:
    workbook = tmp_path / "creator-export.xlsx"
    workbook.write_bytes(b"temporary")

    asyncio.run(export_download.delete_download(FakeDeleteFailureDownload(workbook)))

    assert not workbook.exists()


def test_rejects_oversized_playwright_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = tmp_path / "creator-export.bin"
    workbook.write_bytes(b"too-large")
    monkeypatch.setattr(export_download, "CREATOR_EXPORT_MAX_BYTES", 4)

    with pytest.raises(export_download.CreatorExportDownloadError) as error:
        asyncio.run(export_download._read_download(FakeDownload(workbook)))

    assert error.value.category == "creator_export_size_limit"


def test_creator_export_refreshes_avatar_identities_after_metrics_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    download = object()
    records = [object(), object()]
    metric = SimpleNamespace(username_normalized="creator")
    mapped_page = SimpleNamespace(records=(metric,), raw_payload={})

    async def collect(page, query, tenant_id, **kwargs):
        calls.append(("collect", page, query, tenant_id, kwargs))
        return SimpleNamespace(records=records, expected_total=1)

    source = SimpleNamespace(expected_total=1)

    async def prepare_source(page, trigger):
        calls.append(("prepare_source", page, trigger))
        return source

    class Capture:
        tenant_id = "tenant-1"

        async def persist_mapped_page(self, page, *, platform_shop_id):
            calls.append(("persist", page, platform_shop_id))

        async def finalize_resource(self, resource, snapshot):
            calls.append(("finalize", resource, snapshot["status"]))

        async def refresh_identities(self, query, values):
            calls.append(("refresh", query, values))
            return len(values)

    async def fetch(page):
        return b"xlsx", "file-id", download, "request-id"

    async def cleanup(value):
        calls.append(("cleanup", value))

    monkeypatch.setattr(export_sync, "collect_creator_identity_sample", collect)
    monkeypatch.setattr(export_sync, "prepare_creator_identity_source", prepare_source)
    monkeypatch.setattr(export_sync, "download_creator_export", fetch)
    monkeypatch.setattr(
        export_sync,
        "parse_affiliate_creator_export",
        lambda content, currency: [{"username": "@creator"}],
    )
    monkeypatch.setattr(
        export_sync,
        "map_browser_export_creator_page",
        lambda *args, **kwargs: mapped_page,
    )
    monkeypatch.setattr(export_sync, "delete_download", cleanup)
    page_object = SimpleNamespace(
        url=(
            "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
            "?shop_id=platform-shop-1"
        )
    )
    query = SimpleNamespace(currency="USD", shop_id=uuid4())
    prepared = SimpleNamespace(
        page=page_object,
        query=query,
        trigger="bound-trigger",
    )

    asyncio.run(export_sync.sync_creator_export(prepared, Capture()))

    assert calls == [
        ("prepare_source", page_object, "bound-trigger"),
        ("persist", mapped_page, "platform-shop-1"),
        ("finalize", "creators", "complete"),
        (
            "collect",
            page_object,
            query,
            "tenant-1",
            {
                "max_pages": 30,
                "request_interval": 0.2,
                "target_usernames": frozenset({"creator"}),
                "trigger": None,
                "source": source,
            },
        ),
        ("refresh", query, records),
        ("cleanup", download),
    ]


def test_creator_avatar_refresh_can_be_disabled_for_bounded_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AFFILIATE_CREATOR_AVATAR_REFRESH", "0")

    assert export_sync._avatar_refresh_enabled() is False


def test_export_records_are_reconciled_only_when_full_sample_matches_source() -> None:
    first = SimpleNamespace(username_normalized="creator-one")
    missing = SimpleNamespace(username_normalized="creator-two")
    sample = SimpleNamespace(records=[first, missing], expected_total=2)

    records, added = export_sync._reconcile_export_records((first,), sample, 2)

    assert records == (first, missing)
    assert added == 1


def test_creator_export_completes_after_exact_list_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_record = SimpleNamespace(username_normalized="creator-one")
    missing_record = SimpleNamespace(username_normalized="creator-two")
    snapshots = []
    persisted = []

    @dataclass(frozen=True)
    class MappedPage:
        records: tuple
        raw_payload: dict

    class Capture:
        tenant_id = "tenant-1"

        async def persist_mapped_page(self, page, *, platform_shop_id):
            persisted.append((page, platform_shop_id))

        async def finalize_resource(self, resource, snapshot):
            snapshots.append((resource, snapshot))

    async def fetch(page):
        return b"xlsx", "file-id", object(), "request-id"

    source = SimpleNamespace(expected_total=2)

    async def collect(page, query, tenant_id, **kwargs):
        assert kwargs["collect_all"] is True
        assert kwargs["source"] is source
        return SimpleNamespace(
            records=[export_record, missing_record],
            expected_total=2,
        )

    async def prepare_source(page, trigger):
        return source

    monkeypatch.setenv("AFFILIATE_CREATOR_AVATAR_REFRESH", "0")
    monkeypatch.setattr(export_sync, "download_creator_export", fetch)
    monkeypatch.setattr(export_sync, "collect_creator_identity_sample", collect)
    monkeypatch.setattr(export_sync, "prepare_creator_identity_source", prepare_source)
    monkeypatch.setattr(
        export_sync,
        "parse_affiliate_creator_export",
        lambda content, currency: [{"username": "@creator-one"}],
    )
    monkeypatch.setattr(
        export_sync,
        "map_browser_export_creator_page",
        lambda *args, **kwargs: MappedPage((export_record,), {}),
    )
    monkeypatch.setattr(
        export_sync, "delete_download", lambda download: asyncio.sleep(0)
    )
    prepared = SimpleNamespace(
        page=SimpleNamespace(
            url=(
                "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
                "?shop_id=platform-shop-1"
            )
        ),
        query=SimpleNamespace(currency="USD", shop_id=uuid4()),
        trigger="bound-trigger",
    )

    asyncio.run(export_sync.sync_creator_export(prepared, Capture()))

    assert len(persisted[0][0].records) == 2
    assert persisted[0][0].raw_payload["reconciliation"]["recordsAdded"] == 1
    assert snapshots[0][1]["status"] == "complete"
    assert snapshots[0][1]["records_unique"] == 2


def test_creator_export_uses_tiktok_total_and_marks_truncated_file_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = []
    download = object()
    metric = SimpleNamespace(username_normalized="creator")
    mapped_page = SimpleNamespace(records=(metric,), raw_payload={})

    class Capture:
        tenant_id = "tenant-1"

        async def persist_mapped_page(self, page, *, platform_shop_id):
            return None

        async def finalize_resource(self, resource, snapshot):
            snapshots.append((resource, snapshot))

        async def refresh_identities(self, query, values):
            return len(values)

    async def fetch(page):
        return b"xlsx", "file-id", download, "request-id"

    async def collect(page, query, tenant_id, **kwargs):
        return SimpleNamespace(records=[], expected_total=2)

    source = SimpleNamespace(expected_total=2)

    async def prepare_source(page, trigger):
        return source

    async def cleanup(value):
        return None

    monkeypatch.setattr(export_sync, "download_creator_export", fetch)
    monkeypatch.setattr(export_sync, "collect_creator_identity_sample", collect)
    monkeypatch.setattr(export_sync, "prepare_creator_identity_source", prepare_source)
    monkeypatch.setattr(
        export_sync,
        "parse_affiliate_creator_export",
        lambda content, currency: [{"username": "@creator"}],
    )
    monkeypatch.setattr(
        export_sync,
        "map_browser_export_creator_page",
        lambda *args, **kwargs: mapped_page,
    )
    monkeypatch.setattr(export_sync, "delete_download", cleanup)
    prepared = SimpleNamespace(
        page=SimpleNamespace(
            url=(
                "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
                "?shop_id=platform-shop-1"
            )
        ),
        query=SimpleNamespace(currency="USD", shop_id=uuid4()),
        trigger="bound-trigger",
    )

    asyncio.run(export_sync.sync_creator_export(prepared, Capture()))

    assert snapshots == [
        (
            "creators",
            {
                "status": "partial",
                "failure_category": "total_count_mismatch",
                "expected_total": 2,
                "pages_fetched": 1,
                "records_received": 1,
                "records_unique": 1,
                "duplicates": 0,
            },
        )
    ]
