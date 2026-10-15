from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.services.sample_raw_batch_validation import (
    validate_stored_raw_pages,
)

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class SampleRawBatch:
    sequence: int
    path: Path
    page_count: int
    expected_total: int | None
    captured_total: int


@dataclass(frozen=True)
class StoredSampleRawPage:
    batch_sequence: int
    page_sequence: int
    payload: Mapping[str, Any]
    request_id: str
    request_page: int | None
    request_cursor: str
    response_has_more: bool
    response_total_count: int | None
    response_observed_at: datetime


class SampleRawBatchStore:
    """Durable, per-shop RAW response spool with monotonic batch sequences."""

    def __init__(self, root: Path, shop_key: str) -> None:
        if not _SAFE_KEY.fullmatch(shop_key):
            raise ValueError("RAW batch shop key is invalid")
        self._shop_path = root / shop_key
        self._shop_path.mkdir(parents=True, exist_ok=True)
        self._state_path = self._shop_path / "state.json"

    def start_batch(self) -> int:
        state = self._read_json(self._state_path, default={"last_sequence": 0})
        sequence = int(state.get("last_sequence", 0)) + 1
        self._write_json(self._state_path, {"last_sequence": sequence})
        path = self._batch_path(sequence)
        path.mkdir(exist_ok=False)
        self._write_json(
            path / "manifest.json",
            {
                "sequence": sequence,
                "status": "capturing",
                "page_count": 0,
                "started_at": _utc_now(),
            },
        )
        return sequence

    def persist_page(
        self,
        batch_sequence: int,
        page_sequence: int,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        request_page: int | None,
        request_cursor: str,
        response_has_more: bool,
        response_total_count: int | None,
        response_observed_at: datetime,
    ) -> None:
        if batch_sequence <= 0 or page_sequence <= 0:
            raise ValueError("RAW batch and page sequences must be positive")
        path = self._batch_path(batch_sequence)
        manifest = self._manifest(path)
        if manifest.get("status") != "capturing":
            raise RuntimeError("RAW batch is not accepting pages")
        if (
            not request_id
            or not request_cursor
            or (request_page is not None and request_page < 0)
            or not isinstance(response_has_more, bool)
            or response_observed_at.tzinfo is None
            or (
                response_total_count is not None
                and (response_total_count < 0 or isinstance(response_total_count, bool))
            )
        ):
            raise ValueError("RAW page metadata is invalid")
        canonical = _canonical_json(payload)
        self._write_json(
            path / f"page-{page_sequence:06d}.json",
            {
                "batch_sequence": batch_sequence,
                "page": page_sequence,
                "page_sequence": page_sequence,
                "request_id": request_id,
                "request_page": request_page,
                "request_cursor": request_cursor,
                "response_has_more": response_has_more,
                "response_total_count": response_total_count,
                "response_observed_at": response_observed_at.astimezone(UTC).isoformat(),
                "payload_sha256": hashlib.sha256(canonical).hexdigest(),
                "payload": payload,
            },
        )

    def complete_batch(
        self,
        batch_sequence: int,
        page_count: int,
        *,
        expected_total: int | None,
        captured_total: int,
        terminal_confirmed: bool,
    ) -> SampleRawBatch:
        if page_count <= 0:
            raise ValueError("A completed RAW batch must contain pages")
        path = self._batch_path(batch_sequence)
        manifest = self._manifest(path)
        expected = [path / f"page-{index:06d}.json" for index in range(1, page_count + 1)]
        if manifest.get("status") != "capturing" or not all(
            page.is_file() for page in expected
        ):
            raise RuntimeError("RAW batch is incomplete")
        batch = SampleRawBatch(
            batch_sequence, path, page_count, expected_total, captured_total
        )
        pages = self.load_pages(batch)
        reported_total_count = validate_stored_raw_pages(
            pages,
            expected_total=expected_total,
            captured_total=captured_total,
            terminal_confirmed=terminal_confirmed,
        )
        manifest.update(
            status="completed",
            page_count=page_count,
            expected_total=expected_total,
            reported_total_count=reported_total_count,
            captured_total=captured_total,
            terminal_confirmed=True,
            completed_at=_utc_now(),
        )
        self._write_json(path / "manifest.json", manifest)
        return batch

    def recover_completed(self) -> SampleRawBatch | None:
        for path in sorted(self._shop_path.glob("batch-*")):
            manifest_path = path / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = self._manifest(path)
            if manifest.get("status") == "completed":
                return SampleRawBatch(
                    int(manifest["sequence"]),
                    path,
                    int(manifest["page_count"]),
                    manifest.get("expected_total"),
                    int(manifest["captured_total"]),
                )
        return None

    def abandon_capturing(self, reason: str) -> int:
        if not _SAFE_KEY.fullmatch(reason):
            raise ValueError("RAW batch abandonment reason is invalid")
        abandoned = 0
        for path in sorted(self._shop_path.glob("batch-*")):
            manifest = self._manifest(path)
            if manifest.get("status") != "capturing":
                continue
            manifest.update(status="abandoned", reason=reason, abandoned_at=_utc_now())
            self._write_json(path / "manifest.json", manifest)
            abandoned += 1
        return abandoned

    def load_pages(self, batch: SampleRawBatch) -> tuple[StoredSampleRawPage, ...]:
        pages = []
        completed_at = self._manifest(batch.path).get("completed_at")
        for page_sequence in range(1, batch.page_count + 1):
            envelope = self._read_json(
                batch.path / f"page-{page_sequence:06d}.json"
            )
            payload = envelope.get("payload")
            if (
                envelope.get("batch_sequence") != batch.sequence
                or envelope.get("page_sequence") != page_sequence
                or not isinstance(payload, Mapping)
                or envelope.get("payload_sha256")
                != hashlib.sha256(_canonical_json(payload)).hexdigest()
            ):
                raise RuntimeError("RAW batch page integrity check failed")
            request_id = envelope.get("request_id")
            request_page = envelope.get("request_page")
            request_cursor = envelope.get("request_cursor")
            response_has_more = envelope.get("response_has_more")
            response_total_count = envelope.get("response_total_count")
            response_observed_at = envelope.get("response_observed_at", completed_at)
            if (
                not isinstance(request_id, str)
                or not isinstance(request_cursor, str)
                or (request_page is not None and not isinstance(request_page, int))
                or not isinstance(response_has_more, bool)
                or not isinstance(response_observed_at, str)
                or (
                    response_total_count is not None
                    and not isinstance(response_total_count, int)
                )
            ):
                raise RuntimeError("RAW batch page metadata is invalid")
            observed_at = datetime.fromisoformat(response_observed_at)
            if observed_at.tzinfo is None:
                raise RuntimeError("RAW batch observation time is invalid")
            pages.append(
                StoredSampleRawPage(
                    batch_sequence=batch.sequence,
                    page_sequence=page_sequence,
                    payload=payload,
                    request_id=request_id,
                    request_page=request_page,
                    request_cursor=request_cursor,
                    response_has_more=response_has_more,
                    response_total_count=response_total_count,
                    response_observed_at=observed_at.astimezone(UTC),
                )
            )
        return tuple(pages)

    def acknowledge(self, batch: SampleRawBatch) -> None:
        manifest = self._manifest(batch.path)
        if manifest.get("status") != "completed":
            raise RuntimeError("Only a completed RAW batch can be acknowledged")
        manifest.update(status="processed", processed_at=_utc_now())
        self._write_json(batch.path / "manifest.json", manifest)

    def supersede_completed(
        self, batch: SampleRawBatch, *, reason="server_has_newer_source"
    ) -> None:
        manifest = self._manifest(batch.path)
        if manifest.get("status") != "completed":
            raise RuntimeError("Only a completed RAW batch can be superseded")
        manifest.update(
            status="superseded", reason=reason, superseded_at=_utc_now()
        )
        self._write_json(batch.path / "manifest.json", manifest)

    def _batch_path(self, sequence: int) -> Path:
        return self._shop_path / f"batch-{sequence:012d}"

    def _manifest(self, path: Path) -> dict[str, Any]:
        manifest = self._read_json(path / "manifest.json")
        if not isinstance(manifest, dict):
            raise TypeError("RAW batch manifest is invalid")
        return manifest

    @staticmethod
    def _read_json(path: Path, *, default: Any = None) -> Any:
        if not path.exists() and default is not None:
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        temporary = path.with_name(f"{path.name}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
