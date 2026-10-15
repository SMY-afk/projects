from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date

from erp_api.services.tiktok_transport import TikTokRequest

Sleep = Callable[[float], Awaitable[None]]
_MAX_EXPORT_BYTES = 25 * 1024 * 1024
_WINDOW_TYPES = {1: "PAST_24H", 7: "PAST_7_DAYS", 30: "PAST_30_DAYS"}


class CompassExportError(RuntimeError):
    pass


class CompassExportFailed(CompassExportError):
    pass


@dataclass(frozen=True)
class CompassExport:
    task_id: str
    file_name: str | None
    content: bytes


class HttpTikTokCompassClient:
    def __init__(
        self,
        transport,
        *,
        sleep: Sleep = asyncio.sleep,
        poll_interval_seconds: float = 2.0,
        max_polls: int = 60,
        reuse_existing: bool = False,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._poll_interval = poll_interval_seconds
        self._max_polls = max_polls
        self._reuse_existing = reuse_existing

    async def export_creators(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        window_start: date,
        window_end: date,
    ) -> CompassExport:
        window_type = _window_type(window_start, window_end)
        if self._reuse_existing:
            existing = await self._existing_task(
                access_token, shop_cipher, window_start, window_end
            )
            if existing is not None:
                task_id = str(existing["id"])
                task = (
                    existing
                    if str(existing.get("status", "")).upper() == "SUCCEEDED"
                    else await self._wait_for_task(access_token, shop_cipher, task_id)
                )
                _require_task_window(task, window_start, window_end)
                return CompassExport(
                    task_id=task_id,
                    file_name=str(task.get("file_name") or "") or None,
                    content=await self.download_task(
                        access_token, shop_cipher, task_id
                    ),
                )
        created = await self._transport.request(
            TikTokRequest(
                "POST",
                "/affiliate_seller/202603/compass/offline_task",
                query={"shop_cipher": shop_cipher},
                json_body={
                    "module_type": "CREATOR",
                    "window_type": window_type,
                    "end_day": int(window_end.strftime("%Y%m%d")),
                    "plan_type": "ALL",
                },
                retryable=False,
            ),
            access_token=access_token,
        )
        task_id = _task_id(created)
        task = await self._wait_for_task(access_token, shop_cipher, task_id)
        _require_task_window(task, window_start, window_end)
        content = await self.download_task(access_token, shop_cipher, task_id)
        file_name = task.get("file_name")
        return CompassExport(
            task_id=task_id,
            file_name=file_name if isinstance(file_name, str) else None,
            content=content,
        )

    async def _existing_task(self, token, cipher, start, end):
        suffix = f"_{start:%Y%m%d}-{end:%Y%m%d}"
        for task in await self.list_creator_tasks(token, cipher):
            file_name = task.get("file_name")
            status = str(task.get("status", "")).upper()
            if (
                isinstance(task.get("id"), str)
                and isinstance(file_name, str)
                and file_name.endswith(suffix)
                and status in {"RUNNING", "SUCCEEDED"}
            ):
                return task
        return None

    async def list_creator_tasks(self, token: str, cipher: str) -> list[Mapping[str, object]]:
        payload = await self._transport.request(
            TikTokRequest(
                "GET",
                "/affiliate_seller/202603/compass/offline_tasks",
                query={"shop_cipher": cipher, "doc_type": "CREATOR"},
            ),
            access_token=token,
        )
        tasks = _nested(payload, "data", "tasks")
        if not isinstance(tasks, list):
            raise CompassExportError("TikTok Compass returned an invalid task list.")
        return [task for task in tasks if isinstance(task, Mapping)]

    async def _wait_for_task(self, token, cipher, task_id) -> Mapping[str, object]:
        for attempt in range(self._max_polls):
            task = next(
                (
                    item
                    for item in await self.list_creator_tasks(token, cipher)
                    if item.get("id") == task_id
                ),
                None,
            )
            if task is not None:
                status = str(task.get("status", "")).upper()
                if status == "SUCCEEDED":
                    return task
                if status == "FAILED":
                    raise CompassExportFailed("TikTok Compass export task failed.")
            if attempt + 1 < self._max_polls:
                await self._sleep(self._poll_interval)
        raise CompassExportError("TikTok Compass export task timed out.")

    async def download_task(self, token: str, cipher: str, task_id: str) -> bytes:
        payload = await self._transport.request(
            TikTokRequest(
                "GET",
                f"/affiliate_seller/202603/compass/offline_tasks/{task_id}/file",
                query={"shop_cipher": cipher},
            ),
            access_token=token,
        )
        encoded = _nested(payload, "data", "file", "base64")
        if not isinstance(encoded, str) or not encoded:
            raise CompassExportError("TikTok Compass export file is missing.")
        if len(encoded) > (_MAX_EXPORT_BYTES * 4 // 3) + 4:
            raise CompassExportError("TikTok Compass export file is too large.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise CompassExportError("TikTok Compass export file is invalid.") from error
        if len(content) > _MAX_EXPORT_BYTES or not content.startswith(b"PK\x03\x04"):
            raise CompassExportError("TikTok Compass export is not a valid XLSX file.")
        return content


def _window_type(start: date, end: date) -> str:
    days = (end - start).days + 1
    if days not in _WINDOW_TYPES:
        raise ValueError("TikTok Compass creator window must be 1, 7, or 30 days.")
    return _WINDOW_TYPES[days]


def _task_id(payload: Mapping[str, object]) -> str:
    value = _nested(payload, "data", "task", "id")
    if not isinstance(value, str) or not value:
        raise CompassExportError("TikTok Compass did not return a task ID.")
    return value


def _require_task_window(task: Mapping[str, object], start: date, end: date) -> None:
    file_name = task.get("file_name")
    suffix = f"_{start:%Y%m%d}-{end:%Y%m%d}"
    normalized = str(file_name or "")
    if normalized.lower().endswith(".xlsx"):
        normalized = normalized[:-5]
    if not normalized.endswith(suffix):
        raise CompassExportError(
            "TikTok Compass export task window does not match the requested window."
        )


def _nested(value: object, *path: str) -> object:
    current = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
