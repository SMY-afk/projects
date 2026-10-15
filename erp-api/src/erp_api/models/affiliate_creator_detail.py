from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class AffiliateCreatorDetailReport(TenantScoped, Base):
    __tablename__ = "affiliate_creator_detail_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["creator_id", "tenant_id", "shop_id"],
            [
                "affiliate_creators.id",
                "affiliate_creators.tenant_id",
                "affiliate_creators.shop_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["sync_run_id", "tenant_id"],
            ["analytics_sync_runs.id", "analytics_sync_runs.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", "shop_id"),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "creator_id",
            "resource_kind",
            "query_fingerprint",
            "revision_no",
            name="uq_affiliate_creator_detail_revision",
        ),
        CheckConstraint(
            "resource_kind IN ('video', 'live', 'product', 'product_card')",
            name="ck_affiliate_creator_detail_resource",
        ),
        CheckConstraint(
            "status IN ('running', 'complete', 'partial')",
            name="ck_affiliate_creator_detail_status",
        ),
        CheckConstraint(
            "window_end_utc > window_start_utc",
            name="affiliate_creator_detail_reports_check",
        ),
        Index(
            "ix_affiliate_creator_detail_latest",
            "tenant_id",
            "shop_id",
            "creator_id",
            "resource_kind",
            "window_start_utc",
            "window_end_utc",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    creator_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    resource_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    shop_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    filters: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    expected_total: Mapped[int | None] = mapped_column(Integer)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_unique: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completeness_reason: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AffiliateCreatorDetailItem(TenantScoped, Base):
    __tablename__ = "affiliate_creator_detail_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "tenant_id", "shop_id"],
            [
                "affiliate_creator_detail_reports.id",
                "affiliate_creator_detail_reports.tenant_id",
                "affiliate_creator_detail_reports.shop_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "report_id",
            "platform_content_id",
            name="uq_affiliate_creator_detail_item",
        ),
        Index(
            "ix_affiliate_creator_detail_items_report",
            "tenant_id",
            "shop_id",
            "report_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    platform_content_id: Mapped[str] = mapped_column(String(192), nullable=False)
    identity: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    metrics: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    extensions: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    source_request_id: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
