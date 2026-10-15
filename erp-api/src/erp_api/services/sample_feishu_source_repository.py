from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.shop import Shop
from erp_api.services.refundable_identity_guard import refundable_identity_condition
from erp_api.services.sample_official_cooperation_guard import (
    official_sample_cooperation_condition,
)
from erp_api.services.sample_type_policy import (
    REFUNDABLE_ACTIVE_STATUSES,
    sample_activation_condition,
)


@dataclass(frozen=True)
class SampleFeishuSourceRecord:
    application_id: UUID
    tenant_id: UUID
    shop_id: UUID
    shop_name: str
    platform_application_id: str
    source_type: str
    source_capture_id: UUID
    source_observed_at: datetime
    first_seen_at: datetime
    creator_open_id: str | None
    creator_username: str | None
    creator_nickname: str | None
    follower_count: int | None
    creator_gmv_minor: int | None
    creator_gmv_currency: str | None
    creator_level: str | None
    platform_status: str
    product_id: str | None
    product_title: str | None
    sku_id: str | None
    sku_name: str | None
    commission_rate: Decimal | None
    available_quantity: int | None
    feishu_record_id: str | None
    assignment_version: int
    creator_content_count: int | None = None
    creator_ec_video_view: int | None = None
    creator_fulfillment_percentage: Decimal | None = None
    creator_units_sold: int | None = None
    creator_pps: Decimal | None = None
    creator_rating: Decimal | None = None
    creator_profile_snapshot: dict[str, object] | None = None
    tiktok_applied_at: datetime | None = None
    last_sync_at: datetime | None = None
    sync_hash: str | None = None
    sync_status: str = "pending"
    approve_expiration_at: datetime | None = None
    sample_type: str = "free"


def _latest_creator_metrics(*, tenant_id: UUID, shop_id: UUID):
    ranked = (
        select(
            SampleApplication.tenant_id.label("tenant_id"),
            SampleApplication.shop_id.label("shop_id"),
            SampleApplication.creator_open_id.label("creator_open_id"),
            SampleApplication.follower_count.label("follower_count"),
            SampleApplication.creator_gmv_minor.label("creator_gmv_minor"),
            SampleApplication.creator_gmv_currency.label("creator_gmv_currency"),
            SampleApplication.creator_level.label("creator_level"),
            SampleApplication.creator_content_count.label("creator_content_count"),
            SampleApplication.creator_ec_video_view.label("creator_ec_video_view"),
            SampleApplication.creator_fulfillment_percentage.label(
                "creator_fulfillment_percentage"
            ),
            SampleApplication.creator_units_sold.label("creator_units_sold"),
            SampleApplication.creator_pps.label("creator_pps"),
            SampleApplication.creator_rating.label("creator_rating"),
            SampleApplication.creator_profile_snapshot.label(
                "creator_profile_snapshot"
            ),
            func.row_number()
            .over(
                partition_by=(
                    SampleApplication.tenant_id,
                    SampleApplication.shop_id,
                    SampleApplication.creator_open_id,
                ),
                order_by=(
                    SampleApplication.creator_profile_observed_at.desc().nulls_last(),
                    SampleApplication.source_observed_at.desc(),
                    SampleApplication.id.desc(),
                ),
            )
            .label("metric_rank"),
        )
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.creator_open_id.is_not(None),
            SampleApplication.creator_profile_observed_at.is_not(None),
            or_(
                SampleApplication.creator_units_sold.is_not(None),
                SampleApplication.creator_pps.is_not(None),
                SampleApplication.creator_rating.is_not(None),
            ),
        )
        .subquery("ranked_creator_metrics")
    )
    return (
        select(ranked)
        .where(ranked.c.metric_rank == 1)
        .subquery("latest_creator_metrics")
    )


def build_committed_sample_query(
    *,
    tenant_id: UUID,
    shop_id: UUID,
    after_application_id: UUID | None,
    limit: int,
    application_ids: frozenset[UUID] | None = None,
    activation_at: datetime | None = None,
) -> Select:
    if not 1 <= limit <= 500:
        raise ValueError("Sample Feishu source limit must be between 1 and 500.")
    latest = _latest_creator_metrics(tenant_id=tenant_id, shop_id=shop_id)
    statement = (
        select(
            SampleApplication.id,
            SampleApplication.tenant_id,
            SampleApplication.shop_id,
            Shop.shop_name,
            SampleApplication.platform_application_id,
            SampleApplication.source_type,
            SampleApplication.source_capture_id,
            SampleApplication.source_observed_at,
            SampleApplication.first_seen_at,
            SampleApplication.creator_open_id,
            SampleApplication.creator_username,
            SampleApplication.creator_nickname,
            func.coalesce(latest.c.follower_count, SampleApplication.follower_count),
            func.coalesce(
                latest.c.creator_gmv_minor, SampleApplication.creator_gmv_minor
            ),
            func.coalesce(
                latest.c.creator_gmv_currency, SampleApplication.creator_gmv_currency
            ),
            func.coalesce(latest.c.creator_level, SampleApplication.creator_level),
            SampleApplication.platform_status,
            SampleApplication.product_id,
            SampleApplication.product_title,
            SampleApplication.sku_id,
            SampleApplication.sku_name,
            SampleApplication.commission_rate,
            SampleApplication.available_quantity,
            SampleApplicationWorkflow.feishu_record_id,
            SampleApplicationWorkflow.assignment_version,
            func.coalesce(
                latest.c.creator_content_count,
                SampleApplication.creator_content_count,
            ),
            func.coalesce(
                latest.c.creator_ec_video_view,
                SampleApplication.creator_ec_video_view,
            ),
            func.coalesce(
                latest.c.creator_fulfillment_percentage,
                SampleApplication.creator_fulfillment_percentage,
            ),
            func.coalesce(
                latest.c.creator_units_sold,
                SampleApplication.creator_units_sold,
            ),
            func.coalesce(latest.c.creator_pps, SampleApplication.creator_pps),
            func.coalesce(latest.c.creator_rating, SampleApplication.creator_rating),
            func.coalesce(
                AffiliateCreator.extensions["creator_details_summary"][
                    "profile_snapshot"
                ],
                latest.c.creator_profile_snapshot,
                SampleApplication.creator_profile_snapshot,
            ),
            SampleApplication.tiktok_applied_at,
            SampleApplicationWorkflow.last_sync_at,
            SampleApplicationWorkflow.sync_hash,
            SampleApplicationWorkflow.sync_status,
            SampleApplication.approve_expiration_at,
            SampleApplication.sample_type,
        )
        .join(
            SampleApplicationWorkflow,
            and_(
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
                SampleApplicationWorkflow.tenant_id == SampleApplication.tenant_id,
                SampleApplicationWorkflow.shop_id == SampleApplication.shop_id,
            ),
        )
        .join(
            SampleIngestBatch,
            and_(
                SampleIngestBatch.id == SampleApplication.source_capture_id,
                SampleIngestBatch.tenant_id == SampleApplication.tenant_id,
                SampleIngestBatch.shop_id == SampleApplication.shop_id,
            ),
        )
        .join(
            Shop,
            and_(
                Shop.id == SampleApplication.shop_id,
                Shop.tenant_id == SampleApplication.tenant_id,
            ),
        )
        .outerjoin(
            AffiliateCreator,
            and_(
                AffiliateCreator.tenant_id == SampleApplication.tenant_id,
                AffiliateCreator.shop_id == SampleApplication.shop_id,
                AffiliateCreator.creator_open_id == SampleApplication.creator_open_id,
            ),
        )
        .outerjoin(
            latest,
            and_(
                latest.c.tenant_id == SampleApplication.tenant_id,
                latest.c.shop_id == SampleApplication.shop_id,
                latest.c.creator_open_id == SampleApplication.creator_open_id,
            ),
        )
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.is_current_projection.is_(True),
            refundable_identity_condition(SampleApplication),
            official_sample_cooperation_condition(),
            or_(
                SampleApplication.is_approvable.is_(True),
                and_(SampleApplication.sample_type == "refundable",
                     SampleApplication.platform_status.in_(REFUNDABLE_ACTIVE_STATUSES)),
                SampleApplicationWorkflow.feishu_record_id.is_not(None),
            ),
            SampleIngestBatch.status == "complete",
            SampleIngestBatch.finished_at.is_not(None),
        )
        .order_by(SampleApplication.id)
        .limit(limit)
    )
    if after_application_id is not None:
        statement = statement.where(SampleApplication.id > after_application_id)
    if application_ids is not None:
        statement = statement.where(SampleApplication.id.in_(application_ids))
    if activation_at is not None:
        if activation_at.utcoffset() is None:
            raise ValueError("Sample Feishu activation time must include a timezone.")
        statement = statement.where(sample_activation_condition(activation_at))
    return statement


class SampleFeishuSourceRepository:
    """Read committed normalized sample rows for PostgreSQL-to-Feishu sync."""

    def __init__(
        self, database: Database, *, activation_at: datetime | None = None
    ) -> None:
        if activation_at is not None and activation_at.utcoffset() is None:
            raise ValueError("Sample Feishu activation time must include a timezone.")
        self._database = database
        self._activation_at = (
            activation_at.astimezone(UTC) if activation_at is not None else None
        )

    async def list_committed(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        after_application_id: UUID | None = None,
        limit: int = 200,
        application_ids: frozenset[UUID] | None = None,
    ) -> tuple[SampleFeishuSourceRecord, ...]:
        if application_ids == frozenset():
            return ()
        statement = build_committed_sample_query(
            tenant_id=tenant_id,
            shop_id=shop_id,
            after_application_id=after_application_id,
            limit=limit,
            application_ids=application_ids,
            activation_at=self._activation_at,
        )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(SampleFeishuSourceRecord(*row) for row in rows)
