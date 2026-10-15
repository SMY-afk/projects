from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
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


class SampleApplication(TenantScoped, Base):
    __tablename__ = "sample_applications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_capture_id", "tenant_id", "shop_id"],
            [
                "sample_ingest_batches.id",
                "sample_ingest_batches.tenant_id",
                "sample_ingest_batches.shop_id",
            ],
            name="fk_sample_applications_source_capture_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_sample_applications_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform_application_id",
            name="uq_sample_applications_tenant_shop_platform_id",
        ),
        CheckConstraint(
            "sample_type IN ('free', 'refundable')",
            name="ck_sample_applications_sample_type",
        ),
        CheckConstraint(
            "source_type IN ('official_api', 'hubstudio_cdp')",
            name="ck_sample_applications_source_type",
        ),
        CheckConstraint(
            "creator_level IS NULL OR creator_level IN "
            "('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7')",
            name="ck_sample_applications_creator_level",
        ),
        CheckConstraint(
            "creator_profile_source_type IS NULL OR creator_profile_source_type "
            "IN ('official_api', 'hubstudio_cdp')",
            name="ck_sample_applications_creator_profile_source",
        ),
        CheckConstraint(
            "(creator_avatar_object_key IS NULL AND "
            "creator_avatar_source_hash IS NULL AND "
            "creator_avatar_observed_at IS NULL) OR "
            "(creator_avatar_object_key IS NOT NULL AND "
            "creator_avatar_source_hash IS NOT NULL AND "
            "creator_avatar_observed_at IS NOT NULL)",
            name="ck_sample_applications_creator_avatar_bundle",
        ),
        CheckConstraint(
            "(creator_profile_snapshot IS NULL AND "
            "creator_profile_source_type IS NULL AND "
            "creator_profile_observed_at IS NULL) OR "
            "(creator_profile_snapshot IS NOT NULL AND "
            "creator_profile_source_type IS NOT NULL AND "
            "creator_profile_observed_at IS NOT NULL)",
            name="ck_sample_applications_creator_profile_bundle",
        ),
        Index(
            "ix_sample_applications_tenant_shop_status",
            "tenant_id",
            "shop_id",
            "platform_status",
        ),
        Index(
            "ix_sample_applications_source_capture",
            "tenant_id",
            "shop_id",
            "source_capture_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    platform_application_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sample_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="free", server_default="free"
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_capture_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=True
    )
    platform_status: Mapped[str] = mapped_column(String(64), nullable=False)
    creator_open_id: Mapped[str | None] = mapped_column(String(255))
    creator_username: Mapped[str | None] = mapped_column(String(255))
    creator_nickname: Mapped[str | None] = mapped_column(String(255))
    follower_count: Mapped[int | None] = mapped_column(BigInteger)
    creator_gmv_minor: Mapped[int | None] = mapped_column(BigInteger)
    creator_gmv_currency: Mapped[str | None] = mapped_column(String(3))
    creator_level: Mapped[str | None] = mapped_column(String(2))
    creator_content_count: Mapped[int | None] = mapped_column(BigInteger)
    creator_ec_video_view: Mapped[int | None] = mapped_column(BigInteger)
    creator_fulfillment_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 2)
    )
    creator_units_sold: Mapped[int | None] = mapped_column(BigInteger)
    creator_pps: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    creator_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    creator_avatar_object_key: Mapped[str | None] = mapped_column(Text)
    creator_avatar_source_hash: Mapped[str | None] = mapped_column(String(64))
    creator_avatar_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    creator_profile_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    creator_profile_source_type: Mapped[str | None] = mapped_column(String(32))
    creator_profile_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    product_id: Mapped[str | None] = mapped_column(Text)
    product_title: Mapped[str | None] = mapped_column(Text)
    sku_id: Mapped[str | None] = mapped_column(Text)
    sku_name: Mapped[str | None] = mapped_column(Text)
    sku_image_url: Mapped[str | None] = mapped_column(Text)
    product_image_urls: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="'[]'::jsonb"
    )
    is_current_projection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    order_id: Mapped[str | None] = mapped_column(String(128))
    tracking_number: Mapped[str | None] = mapped_column(String(128))
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    available_quantity: Mapped[int | None] = mapped_column(Integer)
    is_approvable: Mapped[bool | None] = mapped_column(Boolean)
    approve_expiration_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    tiktok_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipment_expiration_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    source_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
