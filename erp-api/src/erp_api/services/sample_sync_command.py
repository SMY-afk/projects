from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import and_, select

from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.sample_application_mapper import (
    ACTIVE_SAMPLE_STATUSES,
    TERMINAL_SAMPLE_STATUSES,
)
from erp_api.services.sample_source_policy import SAMPLE_APPLICATION_SCOPE
from erp_api.workers.sample_queue import SAMPLE_QUEUE_NAME


@dataclass(frozen=True)
class SampleSyncTarget:
    shop_id: UUID
    shop_name: str
    auth_status: str | None
    has_access_token: bool
    has_shop_cipher: bool
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class SampleSyncPlan:
    tenant_id: UUID
    shop_id: UUID
    shop_name: str
    source_type: str
    mode: str
    ready: bool
    reason_code: str


class SampleSyncCommandService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def plan(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        source_type: str,
        mode: str,
    ) -> SampleSyncPlan | None:
        if source_type not in {"official_api", "hubstudio_cdp"}:
            raise ValueError("Sample source type is invalid.")
        if mode not in {"active", "terminal", "full"}:
            raise ValueError("Sample sync mode is invalid.")
        target = await self._target(tenant_id, shop_id)
        if target is None:
            return None
        ready, reason_code = _readiness(target, source_type)
        return SampleSyncPlan(
            tenant_id=tenant_id,
            shop_id=shop_id,
            shop_name=target.shop_name,
            source_type=source_type,
            mode=mode,
            ready=ready,
            reason_code=reason_code,
        )

    async def enqueue(self, queue, plan: SampleSyncPlan) -> str:
        if not plan.ready:
            raise ValueError("Sample sync plan is not ready.")
        job_id = (
            f"manual-sample:{plan.tenant_id}:{plan.shop_id}:"
            f"{plan.source_type}:{plan.mode}:{uuid4().hex}"
        )
        function_name, args = sample_sync_job(plan)
        job = await queue.enqueue_job(
            function_name,
            *args,
            _queue_name=SAMPLE_QUEUE_NAME,
            _job_id=job_id,
        )
        if job is None:
            raise RuntimeError("Targeted sample sync job could not be queued.")
        return job_id

    async def _target(
        self, tenant_id: UUID, shop_id: UUID
    ) -> SampleSyncTarget | None:
        statement = (
            select(
                Shop.id,
                Shop.shop_name,
                ShopConnection.auth_status,
                ShopConnection.access_token_ciphertext,
                ShopConnection.shop_ciphertext,
                ShopConnection.scopes,
            )
            .outerjoin(
                ShopConnection,
                and_(
                    ShopConnection.shop_id == Shop.id,
                    ShopConnection.tenant_id == Shop.tenant_id,
                ),
            )
            .where(
                Shop.tenant_id == tenant_id,
                Shop.id == shop_id,
                Shop.platform == "tiktok",
                Shop.status == "active",
            )
        )
        async for session in self._database.session(tenant_id):
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        return SampleSyncTarget(
            shop_id=row.id,
            shop_name=row.shop_name,
            auth_status=row.auth_status,
            has_access_token=bool(row.access_token_ciphertext),
            has_shop_cipher=bool(row.shop_ciphertext),
            scopes=tuple(row.scopes or ()),
        )


def _readiness(target: SampleSyncTarget, source_type: str) -> tuple[bool, str]:
    if source_type == "hubstudio_cdp":
        return False, "hubstudio_listener_required"
    if target.auth_status != "authorized":
        return False, "tiktok_not_authorized"
    if SAMPLE_APPLICATION_SCOPE not in target.scopes:
        return False, "missing_sample_scope"
    if not target.has_access_token:
        return False, "access_token_missing"
    if not target.has_shop_cipher:
        return False, "shop_cipher_missing"
    return True, "ready"


def sample_sync_job(plan: SampleSyncPlan) -> tuple[str, tuple[object, ...]]:
    if plan.mode == "full":
        return (
            "reconcile_sample_applications_job",
            (str(plan.tenant_id), str(plan.shop_id), plan.source_type, False),
        )
    statuses = (
        sorted(ACTIVE_SAMPLE_STATUSES)
        if plan.mode == "active"
        else sorted(TERMINAL_SAMPLE_STATUSES)
    )
    return (
        "sync_sample_applications_job",
        (
            str(plan.tenant_id),
            str(plan.shop_id),
            plan.mode,
            statuses,
            plan.source_type,
            False,
        ),
    )
