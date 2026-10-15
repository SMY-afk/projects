from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from erp_api.services.affiliate_center_capture_policy import (
    sanitize_capture_payload,
)
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSampleTarget,
)
from erp_api.services.hubstudio_sample_types import HubStudioSampleCapture
from erp_api.services.sample_application_group_projection import (
    obsolete_group_application_ids,
)
from erp_api.services.sample_application_upsert import SamplePayloadObservation


@dataclass(frozen=True)
class HubStudioSampleIngestResult:
    status: str
    batch_id: UUID
    page_count: int
    record_count: int
    request_ids: tuple[str, ...]
    application_ids: tuple[UUID, ...] = ()
    changed_application_ids: tuple[UUID, ...] = ()
    obsolete_platform_application_ids: frozenset[str] = frozenset()


@dataclass
class _BatchState:
    target: HubStudioSampleTarget
    batch_id: UUID
    run_id: UUID
    started_at: datetime
    expected_total: int | None = None
    page_count: int = 0
    application_ids: set[str] = field(default_factory=set)
    observations: dict[str, SamplePayloadObservation] = field(default_factory=dict)
    source_record_count: int = 0
    request_ids: list[str] = field(default_factory=list)
    digest: Any = field(default_factory=hashlib.sha256)


class HubStudioSampleIngestService:
    """Persist a CDP batch before normalizing and upserting its application pages."""

    def __init__(
        self,
        audit_repository,
        application_repository,
        *,
        latest_window: bool = False,
        page_limit: int | None = None,
        source_identity: str | None = None,
        source_payload_hash: str | None = None,
        sample_type: str = "free",
    ) -> None:
        if page_limit is not None and (latest_window or page_limit < 1):
            raise ValueError("Sample page limit requires a positive full capture.")
        self._audits = audit_repository
        self._applications = application_repository
        self._latest_window = latest_window
        self._page_limit = page_limit
        self._source_identity = source_identity
        self._source_payload_hash = source_payload_hash
        self._sample_type = sample_type
        self._states: dict[tuple[UUID, UUID, str, str], _BatchState] = {}
        self._lock = asyncio.Lock()

    async def ingest_page(
        self, capture: HubStudioSampleCapture
    ) -> HubStudioSampleIngestResult:
        self._validate_capture(capture)
        key = self._key(capture.target)
        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = await self._start(capture.target)
                self._states[key] = state
            try:
                self._accept_page_metadata(state, capture)
                for raw_application in capture.page.applications:
                    application = self._sanitize_application(raw_application)
                    application_id = str(application["id"])
                    state.source_record_count += 1
                    previous = state.observations.get(application_id)
                    state.observations[application_id] = SamplePayloadObservation(
                        payload=application,
                        observed_at=(
                            previous.observed_at if previous else capture.observed_at
                        ),
                        request_id=capture.page.platform_request_id,
                        source_capture_id=state.batch_id,
                    )
                    state.application_ids.add(application_id)
                    state.digest.update(self._canonical_bytes(application))
            except Exception as error:
                await self._finish_failure(key, state, error)
                raise

            pagination_complete = capture.page.next_page_token is None
            page_limit_reached = (
                self._page_limit is not None and state.page_count >= self._page_limit
            )
            if (
                not pagination_complete
                and not self._latest_window
                and not page_limit_reached
            ):
                return self._result("running", state)

            complete = (
                self._latest_window
                or page_limit_reached
                or state.expected_total is None
                or len(state.application_ids) == state.expected_total
            )
            if not complete:
                await self._finish(
                    state,
                    status="partial",
                    error_code="total_count_mismatch",
                    error_summary=("HubStudio sample application count did not match."),
                    pagination_complete=True,
                )
                self._states.pop(key, None)
                return self._result("partial", state)

            try:
                application_ids = await self._applications.upsert_source_payloads(
                    tenant_id=capture.target.tenant_id,
                    shop_id=capture.target.shop_id,
                    observations=tuple(state.observations.values()),
                    source_type="hubstudio_cdp",
                )
                changed_application_ids = application_ids
                if hasattr(self._applications, "list_source_changed_since"):
                    changed_application_ids = (
                        await self._applications.list_source_changed_since(
                            tenant_id=capture.target.tenant_id,
                            shop_id=capture.target.shop_id,
                            application_ids=application_ids,
                            since=state.started_at,
                        )
                    )
            except Exception as error:
                self._states.pop(key, None)
                await self._finish(
                    state,
                    status="failed",
                    error_code=type(error).__name__[:64],
                    error_summary=(
                        "HubStudio sample application ingest did not complete."
                    ),
                    pagination_complete=True,
                )
                raise

            await self._finish(
                state,
                status="succeeded",
                error_code=None,
                error_summary=None,
                pagination_complete=pagination_complete,
                application_ids=application_ids,
                changed_application_ids=changed_application_ids,
            )
            self._states.pop(key, None)
            return self._result(
                "succeeded",
                state,
                application_ids,
                changed_application_ids,
            )

    async def abort(self, target: HubStudioSampleTarget, reason: str) -> bool:
        """Finish only the named shop's active batch after its listener stops."""
        key = self._key(target)
        async with self._lock:
            state = self._states.pop(key, None)
            if state is None:
                return False
            await self._finish(
                state,
                status="partial" if state.application_ids else "failed",
                error_code=reason[:64],
                error_summary="HubStudio sample application capture stopped.",
                pagination_complete=False,
            )
            return True

    async def _start(self, target: HubStudioSampleTarget) -> _BatchState:
        started_at = datetime.now(UTC)
        batch_id, run_id = await self._audits.start(
            tenant_id=target.tenant_id,
            shop_id=target.shop_id,
            source_type="hubstudio_cdp",
            source_identity=self._source_identity
            or (f"hubstudio:{target.environment_id}:{target.platform_shop_id}"),
            sync_type="source_to_postgres",
            started_at=started_at,
            **({"sample_type": self._sample_type} if self._sample_type != "free" else {}),
        )
        return _BatchState(target, batch_id, run_id, started_at)

    @staticmethod
    def _accept_page_metadata(
        state: _BatchState, capture: HubStudioSampleCapture
    ) -> None:
        total = capture.page.total_count
        if (
            total is not None
            and state.expected_total is not None
            and total != state.expected_total
        ):
            raise ValueError("HubStudio sample pagination total changed.")
        if total is not None:
            state.expected_total = total
        state.page_count += 1
        request_id = capture.page.platform_request_id
        if request_id and request_id not in state.request_ids:
            state.request_ids.append(request_id)

    async def _finish_failure(
        self,
        key: tuple[UUID, UUID, str, str],
        state: _BatchState,
        error: Exception,
    ) -> None:
        self._states.pop(key, None)
        await self._finish(
            state,
            status="partial" if state.application_ids else "failed",
            error_code=type(error).__name__[:64],
            error_summary="HubStudio sample application ingest did not complete.",
            pagination_complete=False,
        )

    async def _finish(
        self,
        state: _BatchState,
        *,
        status: str,
        error_code: str | None,
        error_summary: str | None,
        pagination_complete: bool,
        application_ids: tuple[UUID, ...] = (),
        changed_application_ids: tuple[UUID, ...] = (),
    ) -> None:
        captured_total = len(state.application_ids)
        await self._audits.finish(
            tenant_id=state.target.tenant_id,
            shop_id=state.target.shop_id,
            batch_id=state.batch_id,
            run_id=state.run_id,
            status=status,
            expected_total=state.expected_total,
            captured_total=captured_total,
            page_count=state.page_count,
            payload_hash=state.digest.hexdigest() if captured_total else None,
            request_ids=state.request_ids,
            evidence={
                "source_type": "hubstudio_cdp",
                "sample_type": self._sample_type,
                "source_payload_hash": self._source_payload_hash,
                "environment_id": state.target.environment_id,
                "platform_shop_id": state.target.platform_shop_id,
                "expected_total": state.expected_total,
                "captured_total": captured_total,
                "duplicates_filtered": state.source_record_count - captured_total,
                "pagination_complete": pagination_complete,
                "capture_mode": self._capture_mode(),
                "page_limit": self._page_limit,
                "page_limit_reached": (
                    self._page_limit is not None
                    and state.page_count >= self._page_limit
                ),
                "application_ids": [str(item) for item in application_ids],
                "changed_application_ids": [
                    str(item) for item in changed_application_ids
                ],
                "quarantined_platform_application_ids": sorted(
                    key for key, item in state.observations.items()
                    if item.payload.get("refundable_identity_quarantine") is not None
                ),
                "obsolete_platform_application_ids": sorted(
                    obsolete_group_application_ids(
                        [item.payload for item in state.observations.values()]
                    )
                ),
            },
            error_code=error_code,
            error_summary=error_summary,
            finished_at=datetime.now(UTC),
        )

    def _capture_mode(self) -> str:
        if self._latest_window:
            return "latest_window"
        return "page_window" if self._page_limit is not None else "full"

    @staticmethod
    def _sanitize_application(payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = sanitize_capture_payload(payload)
        if not isinstance(sanitized, dict):
            raise TypeError("HubStudio sample application payload is invalid.")
        return sanitized

    @staticmethod
    def _canonical_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @staticmethod
    def _key(target: HubStudioSampleTarget) -> tuple[UUID, UUID, str, str]:
        return (
            target.tenant_id,
            target.shop_id,
            target.environment_id,
            target.platform_shop_id,
        )

    @staticmethod
    def _validate_capture(capture: HubStudioSampleCapture) -> None:
        if (
            capture.source_type != "hubstudio_cdp"
            or capture.target.official_access_state != "missing_scope"
        ):
            raise ValueError("HubStudio sample capture source is not allowed.")

    @staticmethod
    def _result(
        status: str,
        state: _BatchState,
        application_ids: tuple[UUID, ...] = (),
        changed_application_ids: tuple[UUID, ...] = (),
    ) -> HubStudioSampleIngestResult:
        return HubStudioSampleIngestResult(
            status=status,
            batch_id=state.batch_id,
            page_count=state.page_count,
            record_count=len(state.application_ids),
            request_ids=tuple(state.request_ids),
            application_ids=tuple(dict.fromkeys(application_ids)),
            changed_application_ids=tuple(dict.fromkeys(changed_application_ids)),
            obsolete_platform_application_ids=obsolete_group_application_ids(
                [item.payload for item in state.observations.values()]
            ),
        )
