from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from erp_api.services.sample_assignment_compensation_decision import (
    compensation_decision,
)
from erp_api.services.sample_assignment_type_pools import run_type_pools
from erp_api.services.sample_bd_assignment import (
    AssignmentDecision,
    BdWorkload,
    select_bd_for_level,
)
from erp_api.services.sample_creator_affinity import keep_creator_with_existing_bd

AssignmentItemStatus = Literal["assigned", "blocked", "duplicate"]


@dataclass(frozen=True)
class PendingSampleAssignment:
    tenant_id: UUID
    shop_id: UUID
    application_id: UUID
    creator_level: str | None
    category: str | None
    assignment_key: str
    creator_gmv_minor: int | None = None
    estimated_level_gmv_minor: int | None = None
    sample_type: str = "free"


@dataclass(frozen=True)
class SampleAssignmentItemResult:
    application_id: UUID
    status: AssignmentItemStatus
    decision: AssignmentDecision | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class SampleAutoAssignmentRunResult:
    status: Literal["succeeded", "skipped", "blocked"]
    items: tuple[SampleAssignmentItemResult, ...] = ()
    blocked_reason: str | None = None

    @property
    def assigned_count(self) -> int:
        return sum(item.status == "assigned" for item in self.items)

    @property
    def blocked_count(self) -> int:
        return sum(item.status == "blocked" for item in self.items)

    @property
    def duplicate_count(self) -> int:
        return sum(item.status == "duplicate" for item in self.items)


class SampleBdRosterProvider(Protocol):
    async def list_members(
        self, tenant_id: UUID, shop_id: UUID, *, sample_type: str = "free"
    ) -> Sequence[BdWorkload]: ...


class SampleAssignmentImageGate(Protocol):
    async def blocked_reason(
        self, tenant_id: UUID, shop_id: UUID, application_id: UUID
    ) -> str | None: ...


class SampleAssignmentTransaction(Protocol):
    async def is_assigned(self) -> bool: ...

    async def load_creator_bd_name(self) -> str | None: ...

    async def load_compensation_bd_name(self) -> str | None: ...

    async def load_workloads(
        self, roster: Sequence[BdWorkload]
    ) -> Sequence[BdWorkload]: ...

    async def record_decision(
        self,
        decision: AssignmentDecision,
        *,
        rule_version: str,
    ) -> None: ...


class SampleAutoAssignmentRepository(Protocol):
    async def list_pending(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        application_ids: frozenset[UUID] | None = None,
        exclude_previously_blocked: bool = False,
    ) -> Sequence[PendingSampleAssignment]: ...

    def transaction(
        self, request: PendingSampleAssignment
    ) -> AbstractAsyncContextManager[SampleAssignmentTransaction]: ...


class SampleAutoAssignmentService:
    """Assign one shop's pending samples through an atomic repository boundary."""

    def __init__(
        self,
        repository: SampleAutoAssignmentRepository,
        roster_provider: SampleBdRosterProvider,
        image_gate: SampleAssignmentImageGate,
        *,
        allowed_shop_ids: frozenset[UUID],
        rule_version: str = "bd-v18-current-bd-membership-and-image-required",
    ) -> None:
        if not allowed_shop_ids:
            raise ValueError(
                "Automatic assignment requires an explicit shop allowlist."
            )
        if not rule_version.strip():
            raise ValueError("Automatic assignment rule version must not be empty.")
        self._repository = repository
        self._roster_provider = roster_provider
        self._image_gate = image_gate
        self._allowed_shop_ids = allowed_shop_ids
        self._rule_version = rule_version

    async def has_pending(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: frozenset[UUID] | None = None,
    ) -> bool:
        if shop_id not in self._allowed_shop_ids:
            return False
        return bool(
            await self._repository.list_pending(
                tenant_id,
                shop_id,
                application_ids=application_ids,
                exclude_previously_blocked=True,
            )
        )

    async def run_for_shop(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: frozenset[UUID] | None = None,
    ) -> SampleAutoAssignmentRunResult:
        if shop_id not in self._allowed_shop_ids:
            return SampleAutoAssignmentRunResult(
                status="skipped", blocked_reason="shop_not_allowed"
            )
        if application_ids is None:
            pending = tuple(await self._repository.list_pending(tenant_id, shop_id))
        else:
            pending = tuple(
                await self._repository.list_pending(
                    tenant_id,
                    shop_id,
                    application_ids=application_ids,
                )
            )
        for request in pending:
            self._validate_request_scope(request, tenant_id, shop_id)
        return await run_type_pools(self, pending, tenant_id, shop_id)

    async def _assign_one(
        self,
        request: PendingSampleAssignment,
        roster: Sequence[BdWorkload],
    ) -> SampleAssignmentItemResult:
        async with self._repository.transaction(request) as transaction:
            if await transaction.is_assigned():
                return SampleAssignmentItemResult(
                    application_id=request.application_id,
                    status="duplicate",
                )
            creator_bd_name = await transaction.load_creator_bd_name()
            workloads = await transaction.load_workloads(roster)
            if creator_bd_name is not None:
                decision = keep_creator_with_existing_bd(
                    request, workloads, creator_bd_name
                )
            else:
                compensation_bd = await transaction.load_compensation_bd_name()
                decision = (
                    compensation_decision(request, workloads, compensation_bd)
                    if compensation_bd is not None
                    else None
                ) or self._decision(request, workloads)
            await transaction.record_decision(
                decision,
                rule_version=self._rule_version_for(request),
            )
            if not decision.assigned:
                return SampleAssignmentItemResult(
                    application_id=request.application_id,
                    status="blocked",
                    decision=decision,
                    blocked_reason=decision.blocked_reason,
                )
            return SampleAssignmentItemResult(
                application_id=request.application_id,
                status="assigned",
                decision=decision,
            )

    async def _record_blocked(
        self,
        request: PendingSampleAssignment,
        blocked_reason: str,
    ) -> SampleAssignmentItemResult:
        async with self._repository.transaction(request) as transaction:
            if await transaction.is_assigned():
                return SampleAssignmentItemResult(
                    application_id=request.application_id,
                    status="duplicate",
                )
            decision = AssignmentDecision(
                None,
                request.creator_level or "unclassified",
                blocked_reason,
            )
            await transaction.record_decision(
                decision,
                rule_version=self._rule_version_for(request),
            )
            return SampleAssignmentItemResult(
                application_id=request.application_id,
                status="blocked",
                decision=decision,
                blocked_reason=blocked_reason,
            )

    def _rule_version_for(self, request: PendingSampleAssignment) -> str:
        return ("bd-v19-refundable-independent-rotation"
                if request.sample_type == "refundable" else self._rule_version)

    @staticmethod
    def _decision(
        request: PendingSampleAssignment,
        workloads: Sequence[BdWorkload],
    ) -> AssignmentDecision:
        if request.creator_level is None:
            return AssignmentDecision(None, "unclassified", "invalid_gmv")
        if request.category is None or not request.category.strip():
            return AssignmentDecision(None, request.creator_level, "unknown_category")
        return select_bd_for_level(
            request.creator_level,
            workloads,
            category=request.category,
            assignment_key=request.assignment_key,
            creator_gmv_minor=request.creator_gmv_minor,
            estimated_level_gmv_minor=request.estimated_level_gmv_minor,
        )

    @staticmethod
    def _validate_request_scope(
        request: PendingSampleAssignment,
        tenant_id: UUID,
        shop_id: UUID,
    ) -> None:
        if request.tenant_id != tenant_id or request.shop_id != shop_id:
            raise RuntimeError("Pending sample assignment crossed its requested scope.")
        if request.sample_type not in {"free", "refundable"}:
            raise ValueError("Pending sample assignment sample type is invalid")
        if not request.assignment_key.strip():
            raise ValueError("Pending sample assignment key must not be empty.")
