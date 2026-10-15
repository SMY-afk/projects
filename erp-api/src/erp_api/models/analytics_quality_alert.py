from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class AnalyticsQualityAlert(TenantScoped, Base):
    """Append-only, tenant-scoped evidence of data quality anomalies."""

    __tablename__ = "analytics_quality_alerts"
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
        CheckConstraint(
            "resource_type IN ('video', 'live', "
            "'affiliate_creator', 'affiliate_video', 'affiliate_creator_detail')",
            name="ck_analytics_quality_alerts_resource_type",
        ),
        Index(
            "ix_analytics_quality_alerts_shop_category_detected",
            "shop_id",
            "category",
            "detected_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    platform_external_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
