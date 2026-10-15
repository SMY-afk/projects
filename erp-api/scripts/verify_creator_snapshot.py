from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from sqlalchemy import func, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import (
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.models.shop import Shop


def _arguments():
    parser = argparse.ArgumentParser(description="Verify one creator snapshot safely.")
    parser.add_argument("--shop-name", required=True)
    parser.add_argument("--from", dest="window_start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="window_end", type=date.fromisoformat, required=True)
    return parser.parse_args()


async def _run(args):
    database = Database(get_settings().database_url)
    try:
        async with database.system_session_factory() as session:
            shop = await session.scalar(
                select(Shop).where(
                    Shop.shop_name == args.shop_name,
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                )
            )
            if shop is None:
                raise ValueError("Active TikTok shop was not found.")
            report = await session.scalar(
                select(AffiliateCreatorReport)
                .where(
                    AffiliateCreatorReport.tenant_id == shop.tenant_id,
                    AffiliateCreatorReport.shop_id == shop.id,
                    AffiliateCreatorReport.period_start == args.window_start,
                    AffiliateCreatorReport.period_end == args.window_end,
                    AffiliateCreatorReport.status == "complete",
                )
                .order_by(AffiliateCreatorReport.revision_no.desc())
                .limit(1)
            )
            if report is None:
                raise ValueError("Complete creator report was not found.")
            values = (
                await session.execute(
                    select(
                        func.count(AffiliateCreatorMetric.id),
                        func.coalesce(func.sum(AffiliateCreatorMetric.affiliate_gmv_minor), 0),
                        func.coalesce(
                            func.sum(AffiliateCreatorMetric.estimated_commission_minor), 0
                        ),
                    ).where(AffiliateCreatorMetric.report_id == report.id)
                )
            ).one()
            return {
                "status": report.status,
                "sourceKind": report.source_kind,
                "recordCount": values[0],
                "affiliateGmvMinor": values[1],
                "estimatedCommissionMinor": values[2],
            }
    finally:
        await database.dispose()


def main():
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, default=str, separators=(",", ":")))


if __name__ == "__main__":
    main()
