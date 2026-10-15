from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class AffiliateCreator(TenantScoped, Base):
    __tablename__ = "affiliate_creators"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
            name="fk_affiliate_creators_shop_tenant",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "shop_id",
            name="uq_affiliate_creators_id_tenant_shop",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "username_normalized",
            name="uq_affiliate_creators_shop_username",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "creator_open_id",
            name="uq_affiliate_creators_shop_open_id",
        ),
        Index(
            "ix_affiliate_creators_shop_username",
            "tenant_id",
            "shop_id",
            "username_normalized",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    creator_open_id: Mapped[str | None] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    source_identifiers: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    extensions: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AffiliateCreatorReport(TenantScoped, Base):
    __tablename__ = "affiliate_creator_reports"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "tenant_id",
            "shop_id",
            name="uq_affiliate_creator_reports_id_tenant_shop",
        ),
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
            name="fk_affiliate_creator_reports_shop_tenant",
        ),
        CheckConstraint(
            "window_end_utc > window_start_utc",
            name="ck_affiliate_creator_reports_utc_window",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "query_fingerprint",
            "revision_no",
            name="uq_affiliate_creator_reports_shop_query_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "source_fingerprint",
            "query_fingerprint",
            name="uq_affiliate_creator_reports_shop_source_query",
        ),
        Index(
            "ix_affiliate_creator_reports_shop_period",
            "tenant_id",
            "shop_id",
            "period_start",
            "period_end",
        ),
        Index(
            "ix_affiliate_creator_reports_shop_window",
            "tenant_id",
            "shop_id",
            "window_start_utc",
            "window_end_utc",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    scope_label: Mapped[str] = mapped_column(String(255), nullable=False)
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    window_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    shop_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128))
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    expected_total: Mapped[int | None] = mapped_column(Integer)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_unique: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completeness_reason: Mapped[str | None] = mapped_column(String(64))
    filters: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AffiliateCreatorMetric(TenantScoped, Base):
    __tablename__ = "affiliate_creator_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
            name="fk_affiliate_creator_metrics_shop_tenant",
        ),
        ForeignKeyConstraint(
            ["report_id", "tenant_id", "shop_id"],
            [
                "affiliate_creator_reports.id",
                "affiliate_creator_reports.tenant_id",
                "affiliate_creator_reports.shop_id",
            ],
            ondelete="CASCADE",
            name="fk_affiliate_creator_metrics_report_tenant_shop",
        ),
        ForeignKeyConstraint(
            ["creator_id", "tenant_id", "shop_id"],
            [
                "affiliate_creators.id",
                "affiliate_creators.tenant_id",
                "affiliate_creators.shop_id",
            ],
            ondelete="CASCADE",
            name="fk_affiliate_creator_metrics_creator_tenant_shop",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "report_id",
            "creator_id",
            name="uq_affiliate_creator_metrics_shop_report_creator",
        ),
        Index(
            "ix_affiliate_creator_metrics_report_gmv",
            "tenant_id",
            "shop_id",
            "report_id",
            "affiliate_gmv_minor",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    creator_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    affiliate_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_live_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_video_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_showcase_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_product_items_sold: Mapped[int | None] = mapped_column(BigInteger)
    items_sold: Mapped[int | None] = mapped_column(BigInteger)
    estimated_commission_minor: Mapped[int | None] = mapped_column(BigInteger)
    estimated_flat_fee_minor: Mapped[int | None] = mapped_column(BigInteger)
    average_order_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    showcase_product_count: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_order_count: Mapped[int | None] = mapped_column(BigInteger)
    click_through_rate: Mapped[str | None] = mapped_column(String(32))
    product_impressions: Mapped[int | None] = mapped_column(BigInteger)
    average_affiliate_customers: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    affiliate_live_count: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_video_count: Mapped[int | None] = mapped_column(BigInteger)
    target_collaboration_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    target_collaboration_estimated_commission_minor: Mapped[int | None] = mapped_column(
        BigInteger
    )
    open_collaboration_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    open_collaboration_estimated_commission_minor: Mapped[int | None] = mapped_column(
        BigInteger
    )
    refunded_affiliate_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    refunded_affiliate_product_count: Mapped[int | None] = mapped_column(BigInteger)
    affiliate_follower_count: Mapped[int | None] = mapped_column(BigInteger)
    extensions: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
