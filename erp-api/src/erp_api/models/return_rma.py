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
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.logistics_task import LogisticsTask
    from erp_api.models.return_request import ReturnRequest


class ReturnRma(TenantScoped, Base):
    __tablename__ = "return_rmas"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_return_rmas_id_tenant"),
        UniqueConstraint(
            "tenant_id", "rma_number", name="uq_return_rmas_tenant_number"
        ),
        UniqueConstraint(
            "tenant_id",
            "return_request_id",
            name="uq_return_rmas_tenant_request",
        ),
        ForeignKeyConstraint(
            ["return_request_id", "tenant_id"],
            ["return_requests.id", "return_requests.tenant_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('open', 'in_transit', 'received', 'closed', 'cancelled')",
            name="ck_return_rmas_status",
        ),
        Index("ix_return_rmas_return_request", "return_request_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    return_request_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    rma_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    generated_by_user_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
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
    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": version_id}

    request: Mapped[ReturnRequest] = relationship(back_populates="rma")
    reverse_task: Mapped[LogisticsTask | None] = relationship(
        back_populates="return_rma", uselist=False
    )
