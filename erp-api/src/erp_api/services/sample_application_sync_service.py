from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from erp_api.services.affiliate_center_capture_policy import (
    sanitize_capture_payload,
)
from erp_api.services.sample_application_mapper import (
    ACTIVE_SAMPLE_STATUSES,
    TERMINAL_SAMPLE_STATUSES,
)
from erp_api.services.sample_application_upsert import SamplePayloadObservation
from erp_api.services.sample_creator_enrichment import SampleCreatorEnrichmentService
from erp_api.services.tiktok_transport import TikTokApiError


@dataclass(frozen=True)
class SampleApplicationSyncResult:
    status: str
    page_count: int
    record_count: int
    request_ids: tuple[str, ...]
    performance_enriched_count: int
    performance_error_count: int
    avatar_stored_count: int
    avatar_error_count: int
    application_ids: tuple[UUID, ...] = ()


class SampleApplicationSyncService:
    def __init__(
        self,
        audit_repository,
        application_repository,
        shop_repository,
        client,
        *,
        avatar_storage=None,
    ):
        self._audits = audit_repository
        self._applications = application_repository
        self._shops = shop_repository
        self._client = client
        self._creator_enrichment = SampleCreatorEnrichmentService(
            client, avatar_storage
        )

    async def sync(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        mode: str,
        status: str | None,
        page_size: int = 50,
    ) -> SampleApplicationSyncResult:
        self._validate_scope(mode, status)
        started_at = datetime.now(UTC)
        batch_id, run_id = await self._audits.start(
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_identity=f"sample_applications:{mode}:{status or 'ALL'}",
            sync_type="reconciliation" if mode == "full" else "source_to_postgres",
            started_at=started_at,
        )
        page_count = 0
        record_count = 0
        expected_total = None
        request_ids: list[str] = []
        observations: list[SamplePayloadObservation] = []
        performance_enriched_count = 0
        performance_error_count = 0
        avatar_stored_count = 0
        avatar_error_count = 0
        digest = hashlib.sha256()
        try:
            access_token, shop_cipher = await asyncio.gather(
                self._shops.get_access_token(tenant_id, shop_id),
                self._shops.get_shop_cipher(tenant_id, shop_id),
            )
            if not access_token or not shop_cipher:
                raise RuntimeError(
                    "Authorized TikTok shop credentials are unavailable."
                )
            async for page in self._client.iter_pages(
                access_token,
                shop_cipher=shop_cipher,
                tenant_id=str(tenant_id),
                shop_id=str(shop_id),
                page_size=page_size,
                status=status,
            ):
                page_count += 1
                expected_total = page.total_count
                if (
                    page.platform_request_id
                    and page.platform_request_id not in request_ids
                ):
                    request_ids.append(page.platform_request_id)
                observed_at = datetime.now(UTC)
                raw_payloads = list(page.applications)
                sanitized_payloads = []
                for raw_payload in page.applications:
                    payload = sanitize_capture_payload(raw_payload)
                    if not isinstance(payload, dict):
                        raise TypeError("TikTok sample application payload is invalid.")
                    sanitized_payloads.append(payload)
                if status == "PENDING":
                    enrichment = await self._creator_enrichment.enrich(
                        sanitized_payloads,
                        source_payloads=raw_payloads,
                        access_token=access_token,
                        shop_cipher=shop_cipher,
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        observed_at=observed_at,
                    )
                    performance_enriched_count += enrichment.performance_enriched_count
                    performance_error_count += enrichment.performance_error_count
                    avatar_stored_count += enrichment.avatar_stored_count
                    avatar_error_count += enrichment.avatar_error_count
                    for request_id in enrichment.request_ids:
                        if request_id not in request_ids:
                            request_ids.append(request_id)
                for payload in sanitized_payloads:
                    digest.update(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                    observations.append(
                        SamplePayloadObservation(
                            payload=payload,
                            observed_at=observed_at,
                            request_id=page.platform_request_id,
                            source_capture_id=batch_id,
                        )
                    )
                    record_count += 1
            application_ids = await self._applications.upsert_source_payloads(
                tenant_id=tenant_id,
                shop_id=shop_id,
                observations=observations,
                source_type="official_api",
            )
        except Exception as error:
            error_code = (
                error.code
                if isinstance(error, TikTokApiError)
                else type(error).__name__
            )
            await self._audits.finish(
                tenant_id=tenant_id,
                shop_id=shop_id,
                batch_id=batch_id,
                run_id=run_id,
                status="partial" if record_count else "failed",
                expected_total=expected_total,
                captured_total=record_count,
                page_count=page_count,
                payload_hash=digest.hexdigest() if record_count else None,
                request_ids=request_ids,
                evidence=self._evidence(
                    mode,
                    status,
                    expected_total,
                    record_count,
                    False,
                    performance_enriched_count,
                    performance_error_count,
                    avatar_stored_count,
                    avatar_error_count,
                ),
                error_code=error_code,
                error_summary="Sample application sync did not complete.",
                finished_at=datetime.now(UTC),
            )
            raise
        await self._audits.finish(
            tenant_id=tenant_id,
            shop_id=shop_id,
            batch_id=batch_id,
            run_id=run_id,
            status="succeeded",
            expected_total=expected_total,
            captured_total=record_count,
            page_count=page_count,
            payload_hash=digest.hexdigest(),
            request_ids=request_ids,
            evidence=self._evidence(
                mode,
                status,
                expected_total,
                record_count,
                True,
                performance_enriched_count,
                performance_error_count,
                avatar_stored_count,
                avatar_error_count,
            ),
            finished_at=datetime.now(UTC),
        )
        return SampleApplicationSyncResult(
            status="succeeded",
            page_count=page_count,
            record_count=record_count,
            request_ids=tuple(request_ids),
            performance_enriched_count=performance_enriched_count,
            performance_error_count=performance_error_count,
            avatar_stored_count=avatar_stored_count,
            avatar_error_count=avatar_error_count,
            application_ids=application_ids,
        )

    @staticmethod
    def _validate_scope(mode: str, status: str | None) -> None:
        allowed = {
            "active": ACTIVE_SAMPLE_STATUSES,
            "terminal": TERMINAL_SAMPLE_STATUSES,
            "full": frozenset({None}),
        }
        if mode not in allowed or status not in allowed[mode]:
            raise ValueError("Sample application poll scope is invalid.")

    @staticmethod
    def _evidence(
        mode: str,
        status: str | None,
        expected_total: int | None,
        captured_total: int,
        complete: bool,
        performance_enriched_count: int,
        performance_error_count: int,
        avatar_stored_count: int,
        avatar_error_count: int,
    ) -> dict[str, object]:
        return {
            "mode": mode,
            "status_filter": status,
            "expected_total": expected_total,
            "captured_total": captured_total,
            "pagination_complete": complete,
            "performance_enriched_count": performance_enriched_count,
            "performance_error_count": performance_error_count,
            "avatar_stored_count": avatar_stored_count,
            "avatar_error_count": avatar_error_count,
        }
