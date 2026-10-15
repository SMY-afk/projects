from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class LogisticsCarrier(TenantScoped, Base):
    __tablename__ = "logistics_carriers"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_logistics_carriers_id_tenant"),
        UniqueConstraint("tenant_id", "code", name="uq_logistics_carriers_tenant_code"),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_logistics_carriers_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_key: Mapped[str] = mapped_column(
        String(64), nullable=False, default="manual", server_default="manual"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    tracking_url_template: Mapped[str | None] = mapped_column(String(1000))
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

    services: Mapped[list[LogisticsCarrierService]] = relationship(
        back_populates="carrier", cascade="all, delete-orphan"
    )
    accounts: Mapped[list[LogisticsCarrierAccount]] = relationship(
        back_populates="carrier", cascade="all, delete-orphan"
    )


class LogisticsCarrierService(TenantScoped, Base):
    __tablename__ = "logistics_carrier_services"
    __table_args__ = (
        ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "carrier_id",
            "tenant_id",
            name="uq_logistics_carrier_services_id_carrier_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "carrier_id",
            "code",
            name="uq_logistics_carrier_services_tenant_carrier_code",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_logistics_carrier_services_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    carrier_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    service_level: Mapped[str | None] = mapped_column(String(64))
    supported_countries: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": version_id}

    carrier: Mapped[LogisticsCarrier] = relationship(back_populates="services")


class LogisticsCarrierAccount(TenantScoped, Base):
    __tablename__ = "logistics_carrier_accounts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "carrier_id",
            "tenant_id",
            name="uq_logistics_carrier_accounts_id_carrier_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "carrier_id",
            "account_name",
            name="uq_logistics_carrier_accounts_tenant_carrier_name",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'expired')",
            name="ck_logistics_carrier_accounts_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    carrier_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    account_name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_identifier_masked: Mapped[str | None] = mapped_column(String(256))
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    secret_reference: Mapped[str | None] = mapped_column(Text)
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

    carrier: Mapped[LogisticsCarrier] = relationship(back_populates="accounts")
