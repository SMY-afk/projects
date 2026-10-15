from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_assignment_workload_provider import (
    AssignmentWorkloadDetail,
)
from erp_api.services.sample_assignment_summary_service import (
    AssignmentSummaryDetail,
)


class SampleAssignmentSummaryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def assignment_details(
        self, assignment_ids: Collection[UUID]
    ) -> dict[UUID, AssignmentSummaryDetail]:
        if not assignment_ids:
            return {}
        async with self._database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        SampleNotificationOutbox.id,
                        SampleApplication.creator_level,
                        Shop.shop_name,
                        SampleApplication.creator_gmv_minor,
                        SampleApplication.sample_type,
                    )
                    .join(
                        SampleApplication,
                        (SampleApplication.id == SampleNotificationOutbox.sample_application_id)
                        & (SampleApplication.tenant_id == SampleNotificationOutbox.tenant_id),
                    )
                    .join(
                        Shop,
                        (Shop.id == SampleApplication.shop_id)
                        & (Shop.tenant_id == SampleApplication.tenant_id),
                    )
                    .where(SampleNotificationOutbox.id.in_(assignment_ids))
                )
            ).all()
        return {
            assignment_id: AssignmentSummaryDetail(
                creator_level, shop_name, creator_gmv_minor, sample_type
            )
            for assignment_id, creator_level, shop_name, creator_gmv_minor, sample_type in rows
        }

    async def assignment_workload_details(
        self, assignment_ids: Collection[UUID]
    ) -> dict[UUID, AssignmentWorkloadDetail]:
        if not assignment_ids:
            return {}
        async with self._database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        SampleNotificationOutbox.id,
                        SampleApplication.shop_id,
                        SampleApplication.creator_level,
                        SampleApplication.creator_gmv_minor,
                        SampleApplication.sample_type,
                    )
                    .join(
                        SampleApplication,
                        (SampleApplication.id == SampleNotificationOutbox.sample_application_id)
                        & (
                            SampleApplication.tenant_id
                            == SampleNotificationOutbox.tenant_id
                        ),
                    )
                    .where(SampleNotificationOutbox.id.in_(assignment_ids))
                )
            ).all()
        return {
            assignment_id: AssignmentWorkloadDetail(
                shop_id, creator_level, creator_gmv_minor, sample_type
            )
            for assignment_id, shop_id, creator_level, creator_gmv_minor, sample_type in rows
        }

    async def list_shop_names(self, shop_ids: Collection[UUID]) -> tuple[str, ...]:
        if not shop_ids:
            return ()
        async with self._database.system_session_factory() as session:
            names = (
                await session.scalars(
                    select(Shop.shop_name)
                    .where(Shop.id.in_(shop_ids))
                    .order_by(Shop.shop_name)
                )
            ).all()
        return tuple(names)
