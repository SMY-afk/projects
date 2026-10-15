from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.logistics_shipping_records import package_record, waybill_record


class LogisticsPackageRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_packages(
        self, tenant_id: UUID, task_id: UUID
    ) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            packages = await session.scalars(
                _package_select()
                .where(LogisticsPackage.task_id == task_id)
                .order_by(LogisticsPackage.created_at, LogisticsPackage.id)
            )
            return [package_record(item) for item in packages.unique().all()]
        return []

    async def list_waybills(
        self, tenant_id: UUID, package_id: UUID
    ) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            waybills = await session.scalars(
                select(LogisticsWaybill)
                .where(LogisticsWaybill.package_id == package_id)
                .order_by(LogisticsWaybill.created_at.desc(), LogisticsWaybill.id)
            )
            return [waybill_record(item) for item in waybills.all()]
        return []


def _package_select():
    return select(LogisticsPackage).options(selectinload(LogisticsPackage.items))
