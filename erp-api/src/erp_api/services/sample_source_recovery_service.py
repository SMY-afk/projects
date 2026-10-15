from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from erp_api.services.sample_source_policy import SAMPLE_APPLICATION_SCOPE

DisableCdp = Callable[[UUID, UUID, str], Awaitable[None]]


class SampleSourceRecoveryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SampleSourceRecoveryResult:
    status: str
    tenant_id: UUID
    shop_id: UUID
    reconciliation_ran: bool


class SampleSourceRecoveryService:
    """Reconcile official data before disabling one shop's CDP source."""

    def __init__(self, policy_repository, official_sync_service) -> None:
        self._policies = policy_repository
        self._official_sync = official_sync_service

    async def candidates(self) -> list[tuple[UUID, UUID]]:
        return await self._policies.list_recovery_candidates()

    async def recover(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        disable_cdp: DisableCdp | None = None,
    ) -> SampleSourceRecoveryResult:
        access = await self._policies.get_shop_access(tenant_id, shop_id)
        if access is None:
            raise SampleSourceRecoveryError(
                "shop_not_authorized", "TikTok shop is unavailable."
            )
        if SAMPLE_APPLICATION_SCOPE not in access.scopes:
            return self._result("scope_missing", tenant_id, shop_id, False)
        if access.latest_cdp_at is None:
            return self._result("official_only", tenant_id, shop_id, False)
        reconciliation_ran = False
        if not access.official_reconciliation_covers_cdp:
            result = await self._official_sync.sync(
                tenant_id,
                shop_id,
                mode="full",
                status=None,
            )
            reconciliation_ran = True
            if result.status != "succeeded":
                raise SampleSourceRecoveryError(
                    "reconciliation_incomplete",
                    "Official sample reconciliation did not succeed.",
                )
            access = await self._policies.get_shop_access(tenant_id, shop_id)
            if (
                access is None
                or not access.official_reconciliation_covers_cdp
            ):
                raise SampleSourceRecoveryError(
                    "reconciliation_not_covering_cdp",
                    "Official reconciliation does not cover the latest CDP batch.",
                )
        if disable_cdp is not None:
            await disable_cdp(
                tenant_id,
                shop_id,
                "official_reconciliation_complete",
            )
        status = "cdp_disabled" if disable_cdp is not None else "official_reconciled"
        return self._result(status, tenant_id, shop_id, reconciliation_ran)

    @staticmethod
    def _result(
        status: str,
        tenant_id: UUID,
        shop_id: UUID,
        reconciliation_ran: bool,
    ) -> SampleSourceRecoveryResult:
        return SampleSourceRecoveryResult(
            status=status,
            tenant_id=tenant_id,
            shop_id=shop_id,
            reconciliation_ran=reconciliation_ran,
        )
