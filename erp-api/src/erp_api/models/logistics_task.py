from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
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
    from erp_api.models.logistics_package import LogisticsPackage
    from erp_api.models.logistics_task_item import LogisticsTaskItem
    from erp_api.models.logistics_task_operation import LogisticsTaskOperation
    from erp_api.models.logistics_task_review import LogisticsTaskReview
    from erp_api.models.return_rma import ReturnRma


class LogisticsTask(TenantScoped, Base):
    __tablename__ = "logistics_tasks"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_logistics_tasks_id_tenant"),
        UniqueConstraint(
            "tenant_id", "task_number", name="uq_logistics_tasks_tenant_number"
        ),
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_logistics_tasks_priority",
        ),
        CheckConstraint(
            "source_type IN ('sales_order', 'return', 'exchange')",
            name="ck_logistics_tasks_source_type",
        ),
        CheckConstraint(
            "direction IN ('forward', 'reverse')",
            name="ck_logistics_tasks_direction",
        ),
        CheckConstraint(
            "(direction = 'forward' AND source_type = 'sales_order' "
            "AND order_id IS NOT NULL AND return_rma_id IS NULL "
            "AND source_reference_id = order_id) OR "
            "(direction = 'reverse' AND source_type IN ('return', 'exchange') "
            "AND order_id IS NOT NULL AND return_rma_id IS NOT NULL "
            "AND source_reference_id = return_rma_id)",
            name="ck_logistics_tasks_source_link",
        ),
        ForeignKeyConstraint(
            ["return_rma_id", "tenant_id"],
            ["return_rmas.id", "return_rmas.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "return_rma_id", name="uq_logistics_tasks_tenant_rma"
        ),
        CheckConstraint(
            "status IN ('pending_review', 'pending_pack', 'pending_waybill', "
            "'pending_dispatch', 'shipped', 'in_transit', 'delivered', "
            "'exception', 'cancelled')",
            name="ck_logistics_tasks_status",
        ),
        Index(
            "ix_logistics_tasks_filter",
            "tenant_id",
            "status",
            "source_type",
            "created_at",
        ),
        Index(
            "ix_logistics_tasks_center_filter",
            "tenant_id",
            "shop_id",
            "source_type",
            "status",
            "priority",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_number: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, default="forward", server_default="forward"
    )
    source_reference_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    source_number: Mapped[str] = mapped_column(String(128), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    return_rma_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    shop_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_review"
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
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
    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": version_id}

    items: Mapped[list[LogisticsTaskItem]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    operations: Mapped[list[LogisticsTaskOperation]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[LogisticsTaskReview]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    packages: Mapped[list[LogisticsPackage]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    return_rma: Mapped[ReturnRma | None] = relationship(back_populates="reverse_task")
