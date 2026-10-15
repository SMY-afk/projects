from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class TikTokVideoPerformanceSnapshot(TenantScoped, Base):
    """Metrics for one video and one exact shop-local reporting window."""

    __tablename__ = "tiktok_video_performance_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["sync_run_id", "tenant_id"],
            ["analytics_sync_runs.id", "analytics_sync_runs.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["shop_id", "platform_video_id"],
            [
                "tiktok_video_contents.shop_id",
                "tiktok_video_contents.platform_video_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "sync_run_id",
            "platform_video_id",
            name="uq_tiktok_video_performance_run_video",
        ),
        CheckConstraint(
            "window_end > window_start",
            name="ck_tiktok_video_performance_window",
        ),
        CheckConstraint(
            "account_type IN ('ALL', 'OFFICIAL_ACCOUNTS', "
            "'MARKETING_ACCOUNTS', 'AFFILIATE_ACCOUNTS')",
            name="ck_tiktok_video_performance_account_type",
        ),
        Index(
            "ix_tiktok_video_performance_window_lookup",
            "tenant_id",
            "shop_id",
            "window_start",
            "window_end",
            "currency",
            "account_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    sync_run_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    platform_video_id: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_request_id: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
