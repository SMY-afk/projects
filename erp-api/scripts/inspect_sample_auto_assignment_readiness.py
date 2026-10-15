from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.shop import Shop


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.system_session_factory() as session:
            shops = (
                await session.execute(select(Shop).order_by(Shop.shop_name))
            ).scalars()
            for shop in shops:
                pending = await session.scalar(
                    select(func.count())
                    .select_from(SampleApplication)
                    .join(
                        SampleApplicationWorkflow,
                        SampleApplicationWorkflow.sample_application_id
                        == SampleApplication.id,
                    )
                    .where(
                        SampleApplication.tenant_id == shop.tenant_id,
                        SampleApplication.shop_id == shop.id,
                        SampleApplication.platform_status == "PENDING",
                        SampleApplicationWorkflow.assigned_bd_name.is_(None),
                    )
                )
                mapped = await session.scalar(
                    select(func.count())
                    .select_from(SampleApplicationWorkflow)
                    .where(
                        SampleApplicationWorkflow.tenant_id == shop.tenant_id,
                        SampleApplicationWorkflow.shop_id == shop.id,
                        SampleApplicationWorkflow.feishu_record_id.is_not(None),
                        SampleApplicationWorkflow.assigned_bd_name.is_(None),
                    )
                )
                print(
                    json.dumps(
                        {
                            "tenant_id": str(shop.tenant_id),
                            "shop_id": str(shop.id),
                            "shop_name": shop.shop_name,
                            "status": shop.status,
                            "unassigned_pending": pending,
                            "unassigned_mapped": mapped,
                        }
                    )
                )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
