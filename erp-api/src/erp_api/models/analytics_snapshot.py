from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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


class AnalyticsSnapshot(TenantScoped, Base):
    """A reusable daily or hourly analytics result for one shop and metric set."""

    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "shop_id",
            "metric_set",
            "granularity",
            "window_start",
            "window_end",
            "currency",
            name="uq_analytics_snapshots_shop_metric_window_currency",
        ),
        Index(
            "ix_analytics_snapshots_shop_metric_granularity_start",
            "shop_id",
            "metric_set",
            "granularity",
            "window_start",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    metric_set: Mapped[str] = mapped_column(String(64), nullable=False)
    granularity: Mapped[str] = mapped_column(String(8), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_request_id: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TikTokVideoContent(TenantScoped, Base):
    """The latest known, deduplicated TikTok video record for a shop."""

    __tablename__ = "tiktok_video_contents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "shop_id",
            "platform_video_id",
            name="uq_tiktok_video_contents_shop_platform_video",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    platform_video_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fields: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str | None] = mapped_column(String(32))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_request_id: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TikTokLiveSession(TenantScoped, Base):
    """The latest known, deduplicated TikTok live session record for a shop."""

    __tablename__ = "tiktok_live_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "shop_id",
            "platform_live_id",
            name="uq_tiktok_live_sessions_shop_platform_live",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    platform_live_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fields: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str | None] = mapped_column(String(32))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_request_id: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
