from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Download, Locator, Page, Response

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    capture_log,
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_creator_download_cleanup import (
    delete_download,
)

CREATOR_EXPORT_PATH = "/api/v3/insights/affiliate/seller/creator/filter_list/export"
CREATOR_EXPORT_FILE_PREFIX = "/api/v1/insights/export/file/"
CREATOR_EXPORT_DIRECT_FILE_PREFIX = CREATOR_EXPORT_PATH + "/"
CREATOR_EXPORT_BUTTON = "[data-testid='export-button']:visible"
CREATOR_EXPORT_TIMEOUT_MS = 180_000
CREATOR_EXPORT_MAX_BYTES = 25 * 1024 * 1024
_REQUEST_ID_HEADERS = ("request-id", "x-request-id", "x-tt-logid", "x-tt-trace-id")


class CreatorExportDownloadError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


async def download_creator_export(
    page: Page,
    *,
    local_download_dir: Path | None = None,
) -> tuple[bytes, str, Download | None, str | None]:
    download: Download | None = None
    pending_download = asyncio.get_running_loop().create_future()

    def observe_download(item: Download) -> None:
        if not pending_download.done():
            pending_download.set_result(item)

    page.on("download", observe_download)
    try:
        button = await _wait_for_export_button(page)
        capture_started = datetime.now(UTC)
        async with (
            page.expect_response(
                _is_export_response, timeout=CREATOR_EXPORT_TIMEOUT_MS
            ) as export_info,
            page.expect_response(
                _is_export_file_response, timeout=CREATOR_EXPORT_TIMEOUT_MS
            ) as file_info,
        ):
            await button.click()
        export_response = await export_info.value
        file_response = await file_info.value
        export_payload = await _json_payload(export_response)
        file_id = _export_file_id(export_payload)
        _validate_file_response(file_response, file_id)
        try:
            content = await _read_download(None, file_response, page)
        except CreatorExportDownloadError as error:
            if error.category != "creator_export_download_failed":
                raise
            download = await asyncio.wait_for(
                pending_download, timeout=CREATOR_EXPORT_TIMEOUT_MS / 1000
            )
            content = await _read_download(
                download, local_download_dir=local_download_dir,
                captured_after=capture_started,
            )
        return content, file_id, download, await _request_id(export_response)
    except CreatorExportDownloadError:
        if download is not None:
            await delete_download(download)
        raise
    except Exception as error:
        if download is not None:
            await delete_download(download)
        raise CreatorExportDownloadError(
            "creator_export_download_failed", "Creator export download failed"
        ) from error
    finally:
        page.remove_listener("download", observe_download)


async def _wait_for_export_button(page: Page) -> Locator:
    button = page.locator(CREATOR_EXPORT_BUTTON).last
    await button.wait_for(state="visible", timeout=CREATOR_EXPORT_TIMEOUT_MS)
    return button


async def _read_download(
    download: Download | None,
    file_response: Response | None = None,
    page: Page | None = None,
    *,
    local_download_dir: Path | None = None,
    captured_after: datetime | None = None,
) -> bytes:
    if file_response is not None:
        try:
            direct = await asyncio.wait_for(file_response.body(), timeout=15)
        except Exception:  # noqa: BLE001 -- attached CDP can discard the response body
            direct = b""
        if len(direct) > CREATOR_EXPORT_MAX_BYTES:
            raise CreatorExportDownloadError(
                "creator_export_size_limit", "Creator export exceeds the size limit"
            )
        if direct.startswith(b"PK\x03\x04"):
            return direct
        if page is not None:
            try:
                return await asyncio.wait_for(
                    _replay_verified_file(page, file_response), timeout=35
                )
            except CreatorExportDownloadError as error:
                if error.category in {
                    "creator_export_size_limit", "creator_export_response_changed"
                }:
                    raise
            except Exception:  # noqa: BLE001 -- retain browser artifact fallback
                capture_log("affiliate_creator_export_replay_fallback")
    if download is None:
        raise CreatorExportDownloadError(
            "creator_export_download_failed", "Creator XLSX bytes are unavailable"
        )
    try:
        file_path = Path(await download.path())
        try:
            content = await _read_bounded_export(file_path)
        except FileNotFoundError:
            with tempfile.TemporaryDirectory(prefix="affiliate-creator-export-") as folder:
                recovered = Path(folder) / "export.xlsx"
                await download.save_as(recovered)
                content = await _read_bounded_export(recovered)
    except CreatorExportDownloadError:
        raise
    except Exception:
        if file_response is None:
            raise
        content = b""
    if content.startswith(b"PK\x03\x04"):
        return content
    if local_download_dir is not None and captured_after is not None:
        recovered = await _read_exact_browser_download(
            download, local_download_dir, captured_after
        )
        if recovered.startswith(b"PK\x03\x04"):
            return recovered
    raise CreatorExportDownloadError(
        "creator_export_download_failed", "Creator XLSX bytes are unavailable"
    )


async def _read_exact_browser_download(
    download: Download, directory: Path, captured_after: datetime
) -> bytes:
    name = download.suggested_filename
    if (
        not name.lower().endswith(".xlsx")
        or Path(name).name != name
        or "/" in name or "\\" in name
    ):
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator download filename changed"
        )
    root = directory.resolve(strict=True)
    try:
        candidate = (root / name).resolve(strict=True)
    except FileNotFoundError:
        return b""
    if candidate.parent != root:
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator download path changed"
        )
    modified = datetime.fromtimestamp(
        (await asyncio.to_thread(candidate.stat)).st_mtime, UTC
    )
    if not (
        captured_after - timedelta(seconds=10)
        <= modified
        <= datetime.now(UTC) + timedelta(seconds=10)
    ):
        return b""
    return await _read_bounded_export(candidate)


async def _replay_verified_file(page: Page, response: Response) -> bytes:
    if urlsplit(response.url).scheme != "https" or not _is_export_file_response(response):
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator export file URL changed"
        )
    replay = await page.context.request.get(
        response.url, timeout=30_000, max_redirects=0
    )
    try:
        if replay.status != 200:
            raise CreatorExportDownloadError(
                "creator_export_download_failed", "Creator file replay failed"
            )
        content = await replay.body()
        if len(content) > CREATOR_EXPORT_MAX_BYTES:
            raise CreatorExportDownloadError(
                "creator_export_size_limit", "Creator export exceeds the size limit"
            )
        if not content.startswith(b"PK\x03\x04"):
            raise CreatorExportDownloadError(
                "creator_export_download_failed", "Creator file replay was not XLSX"
            )
        return content
    finally:
        await replay.dispose()


async def _read_bounded_export(path: Path) -> bytes:
    if (await asyncio.to_thread(path.stat)).st_size > CREATOR_EXPORT_MAX_BYTES:
        raise CreatorExportDownloadError(
            "creator_export_size_limit", "Creator export exceeds the size limit"
        )
    return await asyncio.to_thread(path.read_bytes)


async def _json_payload(response: Response) -> Mapping[str, object]:
    if response.status != 200:
        raise CreatorExportDownloadError(
            "creator_export_download_failed", "Creator export failed"
        )
    content_type = (await response.header_value("content-type") or "").casefold()
    if not content_type.startswith("application/json"):
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator export content type changed"
        )
    payload = await response.json()
    if not isinstance(payload, Mapping) or payload.get("code") not in (0, "0"):
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator export payload changed"
        )
    return payload


def _export_file_id(payload: Mapping[str, object]) -> str:
    data = payload.get("data")
    value = data.get("file") if isinstance(data, Mapping) else None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", value):
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator export has no safe file ID"
        )
    return value


def _is_export_response(response: Response) -> bool:
    split = urlsplit(response.url)
    return (
        is_affiliate_host(split.hostname)
        and split.path == CREATOR_EXPORT_PATH
        and response.request.method.upper() == "POST"
    )


def _is_export_file_response(response: Response) -> bool:
    split = urlsplit(response.url)
    return is_affiliate_host(split.hostname) and (
        split.path.startswith(CREATOR_EXPORT_FILE_PREFIX)
        or split.path.startswith(CREATOR_EXPORT_DIRECT_FILE_PREFIX)
    )


def _validate_file_response(response: Response, file_id: str) -> None:
    path = urlsplit(response.url).path
    if response.status != 200 or path.rsplit("/", 1)[-1] != file_id:
        raise CreatorExportDownloadError(
            "creator_export_response_changed", "Creator export file response mismatched"
        )


async def _request_id(response: Response) -> str | None:
    for name in _REQUEST_ID_HEADERS:
        value = await response.header_value(name)
        if value:
            return value[:128]
    return None


