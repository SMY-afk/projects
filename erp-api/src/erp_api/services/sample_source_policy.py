from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection

SAMPLE_APPLICATION_SCOPE = "seller.affiliate_collaboration.read"


class SampleSourcePolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SampleShopAccess:
    platform_shop_id: str
    scopes: frozenset[str]
    latest_cdp_at: datetime | None = None
    latest_official_reconciliation_at: datetime | None = None

    @property
    def official_reconciliation_covers_cdp(self) -> bool:
        return (
            self.latest_cdp_at is not None
            and self.latest_official_reconciliation_at is not None
            and self.latest_official_reconciliation_at >= self.latest_cdp_at
        )

    @property
    def requires_official_reconciliation(self) -> bool:
        return (
            SAMPLE_APPLICATION_SCOPE in self.scopes
            and self.latest_cdp_at is not None
            and not self.official_reconciliation_covers_cdp
        )


class SampleSourcePolicyRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_shop_access(
        self, tenant_id: UUID, shop_id: UUID
    ) -> SampleShopAccess | None:
        async with self._database.system_session_factory() as session:
            row = (
                await session.execute(
                    select(Shop.platform_shop_id, ShopConnection.scopes)
                    .join(
                        ShopConnection,
                        (ShopConnection.shop_id == Shop.id)
                        & (ShopConnection.tenant_id == Shop.tenant_id),
                    )
                    .where(
                        Shop.tenant_id == tenant_id,
                        Shop.id == shop_id,
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                        ShopConnection.auth_status == "authorized",
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            latest_cdp_at, latest_official_at = await self._recovery_times(
                session, tenant_id, shop_id
            )
            return SampleShopAccess(
                platform_shop_id=row[0],
                scopes=frozenset(row[1] or []),
                latest_cdp_at=latest_cdp_at,
                latest_official_reconciliation_at=latest_official_at,
            )

    async def list_recovery_candidates(self) -> list[tuple[UUID, UUID]]:
        async with self._database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(Shop.tenant_id, Shop.id, ShopConnection.scopes)
                    .join(
                        ShopConnection,
                        (ShopConnection.shop_id == Shop.id)
                        & (ShopConnection.tenant_id == Shop.tenant_id),
                    )
                    .where(
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                        ShopConnection.auth_status == "authorized",
                    )
                    .order_by(Shop.tenant_id, Shop.id)
                )
            ).all()
            candidates = []
            for tenant_id, shop_id, scopes in rows:
                if SAMPLE_APPLICATION_SCOPE not in (scopes or []):
                    continue
                latest_cdp_at, latest_official_at = await self._recovery_times(
                    session, tenant_id, shop_id
                )
                access = SampleShopAccess(
                    platform_shop_id="",
                    scopes=frozenset(scopes or []),
                    latest_cdp_at=latest_cdp_at,
                    latest_official_reconciliation_at=latest_official_at,
                )
                if access.requires_official_reconciliation:
                    candidates.append((tenant_id, shop_id))
            return candidates

    @staticmethod
    async def _recovery_times(session, tenant_id: UUID, shop_id: UUID):
        latest_cdp_at = await session.scalar(
            select(
                func.max(
                    func.coalesce(
                        SampleIngestBatch.finished_at,
                        SampleIngestBatch.started_at,
                    )
                )
            ).where(
                SampleIngestBatch.tenant_id == tenant_id,
                SampleIngestBatch.shop_id == shop_id,
                SampleIngestBatch.source_type == "hubstudio_cdp",
                SampleIngestBatch.sample_type == "free",
            )
        )
        latest_official_at = await session.scalar(
            select(func.max(SampleSyncRun.finished_at)).where(
                SampleSyncRun.tenant_id == tenant_id,
                SampleSyncRun.shop_id == shop_id,
                SampleSyncRun.source_type == "official_api",
                SampleSyncRun.sample_type == "free",
                SampleSyncRun.sync_type == "reconciliation",
                SampleSyncRun.status == "succeeded",
            )
        )
        return latest_cdp_at, latest_official_at


class SampleSourcePolicy:
    def __init__(self, repository) -> None:
        self._repository = repository

    async def require_hubstudio_fallback(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        platform_shop_id: str,
        official_access_state: str,
        sample_type: str = "free",
    ) -> None:
        if sample_type not in {"free", "refundable"}:
            raise ValueError("Sample source type is invalid")
        if official_access_state != "missing_scope":
            raise SampleSourcePolicyError(
                "stage0_not_confirmed",
                "Stage 0 must explicitly confirm missing_scope before CDP fallback.",
            )
        access = await self._repository.get_shop_access(tenant_id, shop_id)
        if access is None:
            raise SampleSourcePolicyError(
                "shop_not_authorized", "The configured TikTok shop is unavailable."
            )
        if access.platform_shop_id != platform_shop_id:
            raise SampleSourcePolicyError(
                "platform_shop_mismatch",
                "The configured platform shop does not match the ERP shop.",
            )
        # The official free-application scope does not authorize the verified
        # refundable browser protocol. Keep free reconciliation type-isolated.
        if sample_type == "free" and SAMPLE_APPLICATION_SCOPE in access.scopes:
            if access.official_reconciliation_covers_cdp:
                raise SampleSourcePolicyError(
                    "official_api_reconciled",
                    "Official reconciliation covers the latest CDP batch.",
                )
            if access.latest_cdp_at is None:
                raise SampleSourcePolicyError(
                    "official_api_available",
                    "Official sample application API is available for this shop.",
                )
