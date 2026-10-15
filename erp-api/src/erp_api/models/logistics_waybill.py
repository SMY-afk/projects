from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.logistics_package import LogisticsPackage


class LogisticsWaybill(TenantScoped, Base):
    __tablename__ = "logistics_waybills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "tenant_id"],
            ["logistics_packages.id", "logistics_packages.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["service_id", "carrier_id", "tenant_id"],
            [
                "logistics_carrier_services.id",
                "logistics_carrier_services.carrier_id",
                "logistics_carrier_services.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id", "carrier_id", "tenant_id"],
            [
                "logistics_carrier_accounts.id",
                "logistics_carrier_accounts.carrier_id",
                "logistics_carrier_accounts.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_logistics_waybills_id_tenant"),
        UniqueConstraint(
            "tenant_id", "waybill_number", name="uq_logistics_waybills_tenant_number"
        ),
        UniqueConstraint(
            "tenant_id",
            "carrier_id",
            "external_waybill_id",
            name="uq_logistics_waybills_tenant_carrier_external",
        ),
        CheckConstraint(
            "status IN ('created', 'label_ready', 'shipped', 'in_transit', "
            "'delivered', 'exception', 'cancelled')",
            name="ck_logistics_waybills_status",
        ),
        CheckConstraint(
            "tracking_status IS NULL OR tracking_status IN "
            "('info_received', 'picked_up', 'in_transit', 'out_for_delivery', "
            "'delivered', 'exception', 'returned', 'cancelled')",
            name="ck_logistics_waybills_tracking_status",
        ),
        Index(
            "uq_logistics_waybills_current_package",
            "tenant_id",
            "package_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    package_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    carrier_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    service_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    account_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    waybill_number: Mapped[str] = mapped_column(String(40), nullable=False)
    external_waybill_id: Mapped[str | None] = mapped_column(String(128))
    tracking_number_masked: Mapped[str | None] = mapped_column(String(128))
    tracking_number_ciphertext: Mapped[str | None] = mapped_column(Text)
    tracking_number_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    label_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tracking_status: Mapped[str | None] = mapped_column(String(32))
    tracking_occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    tracking_sequence: Mapped[int | None] = mapped_column(BigInteger)
    tracking_last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    tracking_next_poll_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    tracking_poll_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    tracking_poll_error_code: Mapped[str | None] = mapped_column(String(64))
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

    package: Mapped[LogisticsPackage] = relationship(back_populates="waybills")
