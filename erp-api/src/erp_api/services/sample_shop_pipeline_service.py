from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from erp_api.services.sample_notification_order import (
    sync_assignment_record_and_deliver,
)


@dataclass(frozen=True)
class SampleShopPipelineResult:
    status: str
    source_type: str
    source_results: tuple[object, ...]
    auto_assignment_result: object | None
    auto_assignment_projection_result: object | None
    profile_enrichment_result: object | None
    assignment_record_result: object | None
    feishu_result: object | None
    notification_results: tuple[object, ...]


class SampleShopPipelineService:
    """Run one shop's committed source-to-notification pipeline in order."""

    def __init__(
        self,
        source_sync,
        feishu_sync,
        notifications=None,
        auto_assignments=None,
        auto_assignment_projection=None,
        assignment_records=None,
        profile_enrichment=None,
        cooperation_precheck=None,
        group_cleanup=None,
        group_assignment_migration=None,
        work_gate=None,
        business_readiness=None,
    ) -> None:
        assignment_parts = (
            auto_assignments,
            auto_assignment_projection,
            assignment_records,
            profile_enrichment,
        )
        if any(part is None for part in assignment_parts) and any(
            part is not None for part in assignment_parts
        ):
            raise ValueError(
                "Sample auto-assignment and its Feishu projections must be paired."
            )
        self._source_sync = source_sync
        self._feishu_sync = feishu_sync
        self._notifications = notifications
        self._auto_assignments = auto_assignments
        self._auto_assignment_projection = auto_assignment_projection
        self._assignment_records = assignment_records
        self._profile_enrichment = profile_enrichment
        self._cooperation_precheck = cooperation_precheck
        self._group_cleanup = group_cleanup
        self._group_assignment_migration = group_assignment_migration
        self._work_gate = work_gate
        self._business_readiness = business_readiness

    async def run(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        mode: str,
        statuses: list[str | None],
        source_type: str = "official_api",
        dry_run: bool = False,
    ) -> SampleShopPipelineResult:
        if not statuses:
            raise ValueError("Sample shop pipeline statuses must not be empty.")
        if source_type not in {"official_api", "hubstudio_cdp"}:
            raise ValueError("Sample shop pipeline source type is invalid.")
        if dry_run:
            return SampleShopPipelineResult(
                status="dry_run",
                source_type=source_type,
                source_results=(),
                auto_assignment_result=None,
                auto_assignment_projection_result=None,
                profile_enrichment_result=None,
                assignment_record_result=None,
                feishu_result=None,
                notification_results=(),
            )
        if source_type == "hubstudio_cdp":
            raise RuntimeError(
                "HubStudio/CDP collection must use an explicitly bound listener."
            )
        source_results = []
        for status in statuses:
            result = await self._source_sync.sync(
                tenant_id,
                shop_id,
                mode=mode,
                status=status,
            )
            if getattr(result, "status", None) != "succeeded":
                raise RuntimeError("Sample source synchronization is incomplete.")
            source_results.append(result)
        return await self.complete_after_source(
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_type=source_type,
            source_results=tuple(source_results),
        )

    async def complete_after_source(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        source_type: str,
        source_results: tuple[object, ...] = (),
        profile_capture: Callable[[], Awaitable[None]] | None = None,
    ) -> SampleShopPipelineResult:
        if source_type not in {"official_api", "hubstudio_cdp"}:
            raise ValueError("Sample shop pipeline source type is invalid.")
        application_ids = _source_application_ids(source_results)
        obsolete_platform_ids = _source_obsolete_platform_ids(source_results)
        if self._work_gate is not None and not await self._work_gate.has_work(
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_type=source_type,
            source_results=source_results,
            application_ids=application_ids,
            obsolete_platform_application_ids=obsolete_platform_ids,
        ):
            return SampleShopPipelineResult(
                status="skipped",
                source_type=source_type,
                source_results=source_results,
                auto_assignment_result=None,
                auto_assignment_projection_result=None,
                profile_enrichment_result=None,
                assignment_record_result=None,
                feishu_result=None,
                notification_results=(),
            )
        if self._business_readiness is not None:
            await self._business_readiness.require_ready(tenant_id=tenant_id, shop_id=shop_id)
        migrated_application_ids = frozenset()
        if self._group_assignment_migration is not None and obsolete_platform_ids:
            migrated_application_ids = await self._group_assignment_migration.migrate(
                tenant_id=tenant_id,
                shop_id=shop_id,
                obsolete_platform_application_ids=obsolete_platform_ids,
            )
            application_ids = frozenset(
                set(application_ids) | set(migrated_application_ids)
            )
        if self._cooperation_precheck is not None:
            await self._cooperation_precheck.evaluate(
                tenant_id,
                shop_id=shop_id,
                application_ids=application_ids,
            )
        if self._auto_assignments is not None:
            await self._feishu_sync.sync(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=application_ids,
            )
        if profile_capture is not None:
            await profile_capture()
        auto_assignment_result = None
        auto_assignment_projection_result = None
        profile_enrichment_result = None
        assignment_record_result = None
        if self._auto_assignments is not None:
            if self._cooperation_precheck is not None:
                await self._cooperation_precheck.complete_due(tenant_id, shop_id)
            auto_assignment_result = await self._auto_assignments.run_for_shop(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=application_ids or frozenset(),
            )
            if getattr(auto_assignment_result, "status", None) not in {
                "succeeded",
                "skipped",
            }:
                raise RuntimeError("Sample automatic assignment is not ready.")
            auto_assignment_projection_result = (
                await self._auto_assignment_projection.sync(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                )
            )
            assigned_application_ids = frozenset(
                item.application_id
                for item in getattr(auto_assignment_result, "items", ())
                if getattr(item, "status", None) == "assigned"
            )
            assignment_record_result = await self._assignment_records.sync(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=frozenset(
                    set(assigned_application_ids) | set(migrated_application_ids)
                ),
            )
        if self._auto_assignments is not None:
            profile_enrichment_result = await self._profile_enrichment.enrich(
                tenant_id=tenant_id,
                shop_id=shop_id,
            )
        feishu_result = await self._feishu_sync.sync(
            tenant_id=tenant_id,
            shop_id=shop_id,
            application_ids=application_ids,
        )
        if self._cooperation_precheck is not None and self._auto_assignments is None:
            await self._cooperation_precheck.complete_due(tenant_id, shop_id)
        if self._auto_assignments is not None:
            # The final Feishu sync can replace a grouped/deduplicated record. Re-run
            # the business projection so a newly attached row is never left with an
            # empty BD for the reverse poll to read back into PostgreSQL.
            await self._auto_assignment_projection.sync(
                tenant_id=tenant_id,
                shop_id=shop_id,
                verify_current=True,
            )
        if self._group_cleanup is not None and obsolete_platform_ids:
            await self._group_cleanup(
                tenant_id=tenant_id,
                shop_id=shop_id,
                obsolete_platform_application_ids=obsolete_platform_ids,
            )
        notification_results = []
        if self._notifications is not None:
            if self._assignment_records is None:
                raise RuntimeError("Sample assignment record service is unavailable.")
            due = await self._notifications.list_due(
                tenant_id=tenant_id,
                shop_id=shop_id,
            )
            for due_tenant_id, event_id, _attempt_count in due:
                if due_tenant_id != tenant_id:
                    raise RuntimeError("Sample notification tenant scope is invalid.")
                (
                    notification_result,
                    assignment_record_result,
                ) = await sync_assignment_record_and_deliver(
                    self._notifications,
                    self._assignment_records,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    event_id=event_id,
                )
                notification_results.append(notification_result)
        return SampleShopPipelineResult(
            status="succeeded",
            source_type=source_type,
            source_results=source_results,
            auto_assignment_result=auto_assignment_result,
            auto_assignment_projection_result=auto_assignment_projection_result,
            profile_enrichment_result=profile_enrichment_result,
            assignment_record_result=assignment_record_result,
            feishu_result=feishu_result,
            notification_results=tuple(notification_results),
        )


def _source_application_ids(
    source_results: tuple[object, ...],
) -> frozenset[UUID] | None:
    if not source_results:
        return None
    scopes = [getattr(result, "application_ids", None) for result in source_results]
    if any(scope is None for scope in scopes):
        return None
    return frozenset(application_id for scope in scopes for application_id in scope)


def _source_obsolete_platform_ids(
    source_results: tuple[object, ...],
) -> frozenset[str]:
    return frozenset(
        platform_id
        for result in source_results
        for platform_id in getattr(
            result, "obsolete_platform_application_ids", frozenset()
        )
    )
