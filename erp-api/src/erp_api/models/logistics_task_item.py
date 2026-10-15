from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.logistics_task import LogisticsTask


class LogisticsTaskItem(TenantScoped, Base):
    __tablename__ = "logistics_task_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["order_line_id", "tenant_id"],
            ["order_lines.id", "order_lines.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "task_id",
            "tenant_id",
            name="uq_logistics_task_items_id_task_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "task_id",
            "source_line_id",
            name="uq_logistics_task_items_tenant_task_source_line",
        ),
        CheckConstraint(
            "planned_quantity > 0",
            name="ck_logistics_task_items_planned_quantity",
        ),
        CheckConstraint(
            "shipped_quantity >= 0 AND shipped_quantity <= packed_quantity "
            "AND packed_quantity <= planned_quantity",
            name="ck_logistics_task_items_quantity_progress",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    source_line_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    order_line_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    platform_product_id: Mapped[str | None] = mapped_column(String(128))
    platform_sku_id: Mapped[str | None] = mapped_column(String(128))
    seller_sku: Mapped[str | None] = mapped_column(String(128))
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    sku_name: Mapped[str | None] = mapped_column(String(300))
    planned_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    packed_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    shipped_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    task: Mapped[LogisticsTask] = relationship(back_populates="items")
