from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.logistics_task import LogisticsTask
    from erp_api.models.logistics_task_item import LogisticsTaskItem
    from erp_api.models.logistics_waybill import LogisticsWaybill


class LogisticsPackage(TenantScoped, Base):
    __tablename__ = "logistics_packages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_logistics_packages_id_tenant"),
        UniqueConstraint(
            "id",
            "task_id",
            "tenant_id",
            name="uq_logistics_packages_id_task_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "package_number",
            name="uq_logistics_packages_tenant_number",
        ),
        CheckConstraint(
            "(sealed_by_user_id IS NULL) = (sealed_at IS NULL)",
            name="ck_logistics_packages_sealing_audit",
        ),
        CheckConstraint(
            "status IN ('draft', 'packed', 'waybill_created', 'shipped', 'cancelled')",
            name="ck_logistics_packages_status",
        ),
        CheckConstraint(
            "weight_grams IS NULL OR weight_grams > 0",
            name="ck_logistics_packages_weight",
        ),
        CheckConstraint(
            "length_mm IS NULL OR length_mm > 0",
            name="ck_logistics_packages_length",
        ),
        CheckConstraint(
            "width_mm IS NULL OR width_mm > 0",
            name="ck_logistics_packages_width",
        ),
        CheckConstraint(
            "height_mm IS NULL OR height_mm > 0",
            name="ck_logistics_packages_height",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    package_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    weight_grams: Mapped[int | None] = mapped_column(Integer)
    length_mm: Mapped[int | None] = mapped_column(Integer)
    width_mm: Mapped[int | None] = mapped_column(Integer)
    height_mm: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    sealed_by_user_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    task: Mapped[LogisticsTask] = relationship(back_populates="packages")
    items: Mapped[list[LogisticsPackageItem]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )
    waybills: Mapped[list[LogisticsWaybill]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class LogisticsPackageItem(TenantScoped, Base):
    __tablename__ = "logistics_package_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "task_id", "tenant_id"],
            [
                "logistics_packages.id",
                "logistics_packages.task_id",
                "logistics_packages.tenant_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_item_id", "task_id", "tenant_id"],
            [
                "logistics_task_items.id",
                "logistics_task_items.task_id",
                "logistics_task_items.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "package_id",
            "task_item_id",
            name="uq_logistics_package_items_package_task_item",
        ),
        CheckConstraint("quantity > 0", name="ck_logistics_package_items_quantity"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    package_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    task_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    task_item_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    package: Mapped[LogisticsPackage] = relationship(back_populates="items")
    task_item: Mapped[LogisticsTaskItem] = relationship(viewonly=True)
