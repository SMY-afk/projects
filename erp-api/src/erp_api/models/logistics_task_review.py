from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Text,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.logistics_task import LogisticsTask


class LogisticsTaskReview(TenantScoped, Base):
    __tablename__ = "logistics_task_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "result IN ('passed', 'difference', 'damaged', 'quantity_mismatch')",
            name="ck_logistics_task_reviews_result",
        ),
        CheckConstraint(
            "expected_quantity >= 0 AND actual_quantity >= 0",
            name="ck_logistics_task_reviews_quantities",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    result: Mapped[str] = mapped_column(nullable=False)
    expected_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    differences: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    note: Mapped[str | None] = mapped_column(Text)
    reviewer_user_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped[LogisticsTask] = relationship(back_populates="reviews")
