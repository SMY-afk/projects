from __future__ import annotations

from datetime import datetime
from typing import ClassVar
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
    text,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class LogisticsPlatformCarrierMapping(TenantScoped, Base):
    __tablename__ = "logistics_platform_carrier_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["service_id", "carrier_id", "tenant_id"],
            [
                "logistics_carrier_services.id",
                "logistics_carrier_services.carrier_id",
                "logistics_carrier_services.tenant_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_logistics_platform_carrier_mappings_id_tenant",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_logistics_platform_carrier_mappings_status",
        ),
        Index(
            "uq_logistics_platform_carrier_mappings_external_default",
            "tenant_id",
            "store_id",
            "platform",
            "platform_carrier_id",
            unique=True,
            postgresql_where=text("delivery_option_id IS NULL"),
        ),
        Index(
            "uq_logistics_platform_carrier_mappings_external_option",
            "tenant_id",
            "store_id",
            "platform",
            "delivery_option_id",
            "platform_carrier_id",
            unique=True,
            postgresql_where=text("delivery_option_id IS NOT NULL"),
        ),
        Index(
            "uq_logistics_platform_carrier_mappings_carrier_default",
            "tenant_id",
            "store_id",
            "platform",
            "carrier_id",
            unique=True,
            postgresql_where=text("service_id IS NULL AND delivery_option_id IS NULL"),
        ),
        Index(
            "uq_logistics_platform_carrier_mappings_carrier_option",
            "tenant_id",
            "store_id",
            "platform",
            "delivery_option_id",
            "carrier_id",
            unique=True,
            postgresql_where=text(
                "service_id IS NULL AND delivery_option_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_logistics_platform_carrier_mappings_service_default",
            "tenant_id",
            "store_id",
            "platform",
            "service_id",
            unique=True,
            postgresql_where=text(
                "service_id IS NOT NULL AND delivery_option_id IS NULL"
            ),
        ),
        Index(
            "uq_logistics_platform_carrier_mappings_service_option",
            "tenant_id",
            "store_id",
            "platform",
            "delivery_option_id",
            "service_id",
            unique=True,
            postgresql_where=text(
                "service_id IS NOT NULL AND delivery_option_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_logistics_platform_carrier_mappings_lookup",
            "tenant_id",
            "store_id",
            "platform",
            "delivery_option_id",
            "carrier_id",
            "service_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    store_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    carrier_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    service_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(
        String(32), nullable=False, default="GLOBAL", server_default="GLOBAL"
    )
    platform_carrier_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform_carrier_code: Mapped[str | None] = mapped_column(String(128))
    platform_carrier_name: Mapped[str | None] = mapped_column(String(128))
    delivery_option_id: Mapped[str | None] = mapped_column(String(128))
    raw_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": version_id}
