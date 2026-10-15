from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp_api.models.analytics_sync import AnalyticsRawPayload, AnalyticsSyncRun
from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.analytics_sync_types import bounded, optional_utc

_CAPTURE_METADATA_KEY = "_erp_capture"


class _TenantDatabase(Protocol):
    def session(self, tenant_id: UUID): ...


class AnalyticsSyncPageRepositoryMixin:
    _database: _TenantDatabase
    _raw_payload_ttl: timedelta

    async def record_page(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        next_cursor: str | None,
        fetched_count: int,
        persisted_count: int,
        platform_request_id: str | None,
        source_updated_at: datetime | None,
        raw_payload_kind: str,
        raw_payload: dict[str, object],
        latest_available_date: date | None = None,
        page_number: int | None = None,
    ) -> None:
        if fetched_count < 0 or persisted_count < 0:
            raise ValueError("Sync counts cannot be negative.")
        if not raw_payload_kind or len(raw_payload_kind) > 32:
            raise ValueError("raw_payload_kind must contain 1 to 32 characters.")
        request_id = _request_id(platform_request_id or "")
        _validate_page_number(page_number)
        fresh_at = optional_utc(source_updated_at)
        sanitized_payload = sanitize_capture_payload(raw_payload)
        if not isinstance(sanitized_payload, dict):
            raise TypeError("sanitized raw payload must be an object")
        stored_payload = add_capture_metadata(sanitized_payload, page_number)
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status != "running":
                raise RuntimeError("Analytics sync run is not active.")
            await self._lock_page_replay(session, run_id, request_id, page_number)
            if await self._page_is_recorded(
                session,
                tenant_id,
                run.shop_id,
                run_id,
                request_id=request_id,
                raw_payload_kind=raw_payload_kind,
                page_number=page_number,
            ):
                return
            run.recovery_cursor = next_cursor
            run.fetched_count += fetched_count
            run.persisted_count += persisted_count
            run.platform_request_id = bounded(request_id, 128)
            if latest_available_date is not None:
                run.latest_available_date = latest_available_date
            if fresh_at and (
                run.last_source_updated_at is None
                or fresh_at > run.last_source_updated_at
            ):
                run.last_source_updated_at = fresh_at
            session.add(
                AnalyticsRawPayload(
                    tenant_id=tenant_id,
                    shop_id=run.shop_id,
                    sync_run_id=run.id,
                    payload_kind=raw_payload_kind,
                    payload=stored_payload,
                    platform_request_id=bounded(request_id, 128),
                    source_updated_at=fresh_at,
                    expires_at=datetime.now(UTC) + self._raw_payload_ttl,
                )
            )
            await session.commit()
            return
        raise RuntimeError("Tenant database session was not created.")

    async def has_recorded_page(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        run_id: UUID,
        *,
        platform_request_id: str,
        raw_payload_kind: str,
        page_number: int | None = None,
    ) -> bool:
        request_id = _request_id(platform_request_id)
        _validate_page_number(page_number)
        async for session in self._database.session(tenant_id):
            return await self._page_is_recorded(
                session,
                tenant_id,
                shop_id,
                run_id,
                request_id=request_id,
                raw_payload_kind=raw_payload_kind,
                page_number=page_number,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def _lock_page_replay(
        self,
        session: AsyncSession,
        run_id: UUID,
        request_id: str,
        page_number: int | None,
    ) -> None:
        page_identity = (
            f"page:{page_number}"
            if page_number is not None
            else f"request:{request_id}"
        )
        identity = f"{run_id}:{page_identity}"
        lock_key = int.from_bytes(
            sha256(identity.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def _page_is_recorded(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        shop_id: UUID,
        run_id: UUID,
        *,
        request_id: str,
        raw_payload_kind: str,
        page_number: int | None,
    ) -> bool:
        identities = [AnalyticsRawPayload.platform_request_id == request_id]
        if page_number is not None:
            identities.append(
                AnalyticsRawPayload.payload[_CAPTURE_METADATA_KEY][
                    "pageNumber"
                ].as_integer()
                == page_number
            )
        recorded_id = await session.scalar(
            select(AnalyticsRawPayload.id)
            .where(
                AnalyticsRawPayload.tenant_id == tenant_id,
                AnalyticsRawPayload.shop_id == shop_id,
                AnalyticsRawPayload.sync_run_id == run_id,
                AnalyticsRawPayload.payload_kind == raw_payload_kind,
                or_(*identities),
            )
            .limit(1)
        )
        return recorded_id is not None


def add_capture_metadata(
    payload: dict[str, object], page_number: int | None
) -> dict[str, object]:
    _validate_page_number(page_number)
    if page_number is None:
        return payload
    stored = dict(payload)
    stored[_CAPTURE_METADATA_KEY] = {"pageNumber": page_number}
    return stored


def _request_id(value: str) -> str:
    request_id = value.strip()
    if not request_id:
        raise ValueError("platform_request_id is required for page audit records.")
    return request_id[:128]


def _validate_page_number(value: int | None) -> None:
    if value is not None and value < 1:
        raise ValueError("page_number must be positive.")
