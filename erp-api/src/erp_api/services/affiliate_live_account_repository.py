from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Numeric, case, cast, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.analytics_snapshot import TikTokLiveSession
from erp_api.models.scraped_data import ScrapedData
from erp_api.models.shop import Shop
from erp_api.services.analytics_read_repository import StoredAnalyticsContent


@dataclass(frozen=True)
class AffiliateLiveAccountPage:
    items: list[StoredAnalyticsContent]
    total: int
    as_of: datetime | None


class AffiliateLiveAccountRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def shop_exists(self, tenant_id: UUID, shop_id: UUID) -> bool:
        async for session in self._database.session(tenant_id):
            return (
                await session.scalar(select(Shop.id).where(Shop.id == shop_id))
                is not None
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_shop_timezone(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        async for session in self._database.session(tenant_id):
            return await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
        raise RuntimeError("Tenant database session was not created.")

    async def list_page(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        page: int,
        page_size: int,
        sort_by: Literal["gmv", "startedAt"],
        sort_order: Literal["asc", "desc"],
        account_type: str,
        window_start: datetime,
        window_end: datetime,
    ) -> AffiliateLiveAccountPage:
        live_start_text = TikTokLiveSession.fields["startTime"].astext
        live_start = cast(live_start_text, Numeric(20, 4))
        filters = (
            TikTokLiveSession.tenant_id == tenant_id,
            TikTokLiveSession.shop_id == shop_id,
            TikTokLiveSession.fields["accountType"].astext == account_type,
            live_start_text.op("~")(r"^\d+(?:\.\d+)?$"),
            live_start >= window_start.timestamp(),
            live_start < window_end.timestamp(),
        )
        sort_key = "gmvAmount" if sort_by == "gmv" else "startTime"
        sort_text = TikTokLiveSession.fields[sort_key].astext
        sort_value = case(
            (
                sort_text.op("~")(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$"),
                cast(sort_text, Numeric(20, 4)),
            ),
            else_=None,
        )
        ordered = sort_value.asc() if sort_order == "asc" else sort_value.desc()
        async for session in self._database.session(tenant_id):
            total, as_of = (
                await session.execute(
                    select(
                        func.count(TikTokLiveSession.id),
                        func.max(TikTokLiveSession.observed_at),
                    ).where(*filters)
                )
            ).one()
            rows = (
                await session.execute(
                    select(
                        TikTokLiveSession.platform_live_id,
                        TikTokLiveSession.fields,
                        TikTokLiveSession.source_status,
                        TikTokLiveSession.status,
                        TikTokLiveSession.source_updated_at,
                        TikTokLiveSession.observed_at,
                    )
                    .where(*filters)
                    .order_by(
                        ordered.nullslast(),
                        TikTokLiveSession.source_updated_at.desc().nullslast(),
                        TikTokLiveSession.observed_at.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            items = [StoredAnalyticsContent(*row) for row in rows]
            if items:
                platform_shop_id = await session.scalar(
                    select(Shop.platform_shop_id).where(Shop.id == shop_id)
                )
                payloads = (
                    await session.scalars(
                        select(ScrapedData.raw_data)
                        .where(
                            ScrapedData.tenant_id == tenant_id,
                            ScrapedData.data_type == "seller_live_analytics",
                        )
                        .order_by(ScrapedData.updated_at.desc())
                    )
                ).all()
                metrics = seller_live_metrics(
                    payloads,
                    platform_shop_id=platform_shop_id,
                    live_ids={item.platform_external_id for item in items},
                )
                items = [
                    replace(
                        item,
                        fields={
                            **item.fields,
                            **metrics.get(item.platform_external_id, {}),
                        },
                    )
                    for item in items
                ]
            return AffiliateLiveAccountPage(
                items=items,
                total=total,
                as_of=as_of,
            )
        raise RuntimeError("Tenant database session was not created.")


def seller_live_metrics(
    payloads: Sequence[Mapping[str, object]],
    *,
    platform_shop_id: str | None,
    live_ids: set[str],
) -> dict[str, dict[str, object]]:
    """Read the newest captured Seller Center interaction metrics per LIVE."""
    if not platform_shop_id or not live_ids:
        return {}
    result: dict[str, dict[str, object]] = {}
    for payload in payloads:
        data = payload.get("data")
        infos = data.get("infos") if isinstance(data, Mapping) else None
        if not isinstance(infos, list):
            continue
        for info in infos:
            if (
                not isinstance(info, Mapping)
                or str(info.get("shop_id")) != platform_shop_id
            ):
                continue
            live_meta = info.get("live_meta")
            stats = info.get("stats")
            if not isinstance(live_meta, Mapping) or not isinstance(stats, Mapping):
                continue
            live_id = live_meta.get("id")
            live_id = str(live_id) if live_id is not None else ""
            if live_id not in live_ids:
                continue
            current = result.setdefault(live_id, {})
            if "views" not in current and stats.get("views") is not None:
                current["views"] = stats["views"]
            if "clickThroughRate" not in current and stats.get("ctr") is not None:
                current["clickThroughRate"] = stats["ctr"]
    return result
