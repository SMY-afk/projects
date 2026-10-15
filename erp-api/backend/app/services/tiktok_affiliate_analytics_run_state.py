from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.services.tiktok_affiliate_analytics_page_evidence import (
    cursor_hash,
    page_records,
    pagination_cursor,
    pagination_has_more,
)

_RESOURCES = ("creators", "videos")
_TERMINAL_STATUSES = frozenset({"complete", "partial", "failed", "session_required"})


@dataclass(frozen=True)
class CaptureGuardConfig:
    max_pages: int = 200
    max_run_seconds: float = 900
    min_request_interval_seconds: float = 3
    max_consecutive_empty_pages: int = 2

    def __post_init__(self) -> None:
        if self.max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")
        if self.max_run_seconds <= 0:
            raise ValueError("max_run_seconds must be greater than zero.")
        if self.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds cannot be negative.")
        if self.max_consecutive_empty_pages <= 0:
            raise ValueError("max_consecutive_empty_pages must be greater than zero.")


@dataclass(frozen=True)
class PageRecordDecision:
    accepted: bool
    stop: bool


@dataclass
class _ResourceState:
    resource: str
    status: str = "idle"
    expected_total: int | None = None
    pages_fetched: int = 0
    records_received: int = 0
    records_unique: int = 0
    duplicates: int = 0
    consecutive_empty_pages: int = 0
    first_page_index: int | None = None
    last_page_index: int | None = None
    last_cursor_hash: str | None = None
    failure_category: str | None = None
    terminal_reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    started_monotonic: float | None = None
    last_request_monotonic: float | None = None
    seen_pages: set[int] = field(default_factory=set)
    seen_record_keys: set[str] = field(default_factory=set)
    seen_cursor_hashes: set[str] = field(default_factory=set)


class AffiliateAnalyticsRunGuard:
    def __init__(
        self,
        config: CaptureGuardConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or CaptureGuardConfig()
        self._clock = clock
        self._states = {
            resource: _ResourceState(resource=resource) for resource in _RESOURCES
        }

    def record_page(
        self,
        resource: str,
        page_index: int,
        payload: Mapping[str, object],
    ) -> PageRecordDecision:
        state = self._state(resource)
        if state.status in _TERMINAL_STATUSES:
            return PageRecordDecision(accepted=False, stop=True)
        self._start(state)
        if self.enforce_runtime_limit(resource):
            return PageRecordDecision(accepted=False, stop=True)
        if page_index in state.seen_pages:
            return PageRecordDecision(accepted=False, stop=False)

        rows, record_keys, expected_total = page_records(resource, payload)
        if expected_total is not None:
            if (
                state.expected_total is not None
                and state.expected_total != expected_total
            ):
                self.fail(
                    resource,
                    status="failed",
                    category="total_count_changed",
                )
                return PageRecordDecision(accepted=False, stop=True)
            state.expected_total = expected_total
        state.seen_pages.add(page_index)
        state.first_page_index = state.first_page_index or page_index
        state.last_page_index = page_index
        state.pages_fetched += 1
        state.records_received += rows
        for key in record_keys:
            if key in state.seen_record_keys:
                state.duplicates += 1
            else:
                state.seen_record_keys.add(key)
        state.records_unique = len(state.seen_record_keys)
        state.consecutive_empty_pages = (
            state.consecutive_empty_pages + 1 if rows == 0 else 0
        )

        cursor_observed, cursor = pagination_cursor(payload)
        if cursor_observed and cursor:
            hashed_cursor = cursor_hash(cursor)
            state.last_cursor_hash = hashed_cursor
            if hashed_cursor in state.seen_cursor_hashes:
                self.fail(
                    resource,
                    status="partial",
                    category="cursor_interrupted",
                )
                return PageRecordDecision(accepted=True, stop=True)
            state.seen_cursor_hashes.add(hashed_cursor)

        has_more = pagination_has_more(payload)
        if has_more is True and cursor_observed and not cursor:
            self.fail(
                resource,
                status="partial",
                category="cursor_interrupted",
            )
            return PageRecordDecision(accepted=True, stop=True)
        if has_more is False or (cursor_observed and not cursor):
            self._finish_complete_or_partial(state, "payload_terminal")
            return PageRecordDecision(accepted=True, stop=True)
        if (
            resource == "videos"
            and state.expected_total is not None
            and state.records_unique >= state.expected_total
        ):
            self._finish_complete_or_partial(state, "expected_total_reached")
            return PageRecordDecision(accepted=True, stop=True)
        if state.consecutive_empty_pages >= self.config.max_consecutive_empty_pages:
            self.fail(
                resource,
                status="partial",
                category="consecutive_empty_pages",
            )
            return PageRecordDecision(accepted=True, stop=True)
        if state.pages_fetched >= self.config.max_pages:
            self.fail(
                resource,
                status="partial",
                category="max_pages_exceeded",
            )
            return PageRecordDecision(accepted=True, stop=True)
        return PageRecordDecision(accepted=True, stop=False)

    def finish_ui_terminal(self, resource: str) -> None:
        state = self._state(resource)
        if state.status not in _TERMINAL_STATUSES:
            self._finish_complete_or_partial(state, "no_next_page_control")

    def fail(self, resource: str, *, status: str, category: str) -> None:
        if status not in {"partial", "failed", "session_required"}:
            raise ValueError("Invalid terminal failure status.")
        state = self._state(resource)
        if state.status in _TERMINAL_STATUSES:
            return
        self._start(state)
        if state.pages_fetched and status in {"failed", "session_required"}:
            status = "partial"
            category = "page_failed"
        state.status = status
        state.failure_category = category
        state.terminal_reason = category
        state.finished_at = _now_iso()

    def enforce_runtime_limit(self, resource: str) -> bool:
        state = self._state(resource)
        if state.status in _TERMINAL_STATUSES:
            return True
        if state.started_monotonic is None:
            return False
        if self._clock() - state.started_monotonic < self.config.max_run_seconds:
            return False
        self.fail(
            resource,
            status="partial",
            category="max_runtime_exceeded",
        )
        return True

    def remaining_request_delay(self, resource: str) -> float:
        state = self._state(resource)
        reference = state.last_request_monotonic or state.started_monotonic
        if reference is None:
            return 0
        elapsed = self._clock() - reference
        return max(0.0, self.config.min_request_interval_seconds - elapsed)

    def mark_request(self, resource: str) -> None:
        state = self._state(resource)
        if state.status == "running":
            state.last_request_monotonic = self._clock()

    def is_terminal(self, resource: str) -> bool:
        return self._state(resource).status in _TERMINAL_STATUSES

    def snapshot(self, resource: str) -> dict[str, object]:
        state = self._state(resource)
        return {
            "resource": resource,
            "status": state.status,
            "expected_total": state.expected_total,
            "pages_fetched": state.pages_fetched,
            "records_received": state.records_received,
            "records_unique": state.records_unique,
            "duplicates": state.duplicates,
            "consecutive_empty_pages": state.consecutive_empty_pages,
            "first_page_index": state.first_page_index,
            "last_page_index": state.last_page_index,
            "last_cursor_hash": state.last_cursor_hash,
            "failure_category": state.failure_category,
            "terminal_reason": state.terminal_reason,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
        }

    def snapshots(self) -> dict[str, dict[str, object]]:
        return {resource: self.snapshot(resource) for resource in _RESOURCES}

    def _state(self, resource: str) -> _ResourceState:
        try:
            return self._states[resource]
        except KeyError as error:
            raise ValueError("Unknown affiliate analytics resource.") from error

    def _start(self, state: _ResourceState) -> None:
        if state.status == "idle":
            state.status = "running"
            state.started_at = _now_iso()
            state.started_monotonic = self._clock()

    def _finish_complete_or_partial(
        self, state: _ResourceState, terminal_reason: str
    ) -> None:
        if state.first_page_index != 1:
            state.status = "partial"
            state.failure_category = "started_after_first_page"
        elif (
            state.expected_total is not None
            and state.records_unique != state.expected_total
        ):
            state.status = "partial"
            state.failure_category = "total_count_mismatch"
        else:
            state.status = "complete"
            state.failure_category = None
        state.terminal_reason = terminal_reason
        state.finished_at = _now_iso()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
