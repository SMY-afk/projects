from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.order import Order
    from erp_api.models.order_line import OrderLine
    from erp_api.models.return_rma import ReturnRma


class ReturnRequest(TenantScoped, Base):
    __tablename__ = "return_requests"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_return_requests_id_tenant"),
        UniqueConstraint(
            "tenant_id", "request_number", name="uq_return_requests_tenant_number"
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform",
            "platform_return_id",
            name="uq_return_requests_platform_identity",
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
            "request_type IN ('return', 'exchange', 'refund')",
            name="ck_return_requests_type",
        ),
        CheckConstraint(
            "source IN ('local', 'platform')",
            name="ck_return_requests_source",
        ),
        CheckConstraint(
            "(source = 'local' AND platform IS NULL AND platform_return_id IS NULL) OR "
            "(source = 'platform' AND platform IS NOT NULL AND platform_return_id IS NOT NULL)",
            name="ck_return_requests_platform_source",
        ),
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected', 'cancelled')",
            name="ck_return_requests_status",
        ),
        CheckConstraint(
            "(reviewed_by_user_id IS NULL) = (reviewed_at IS NULL)",
            name="ck_return_requests_review_audit",
        ),
        Index(
            "ix_return_requests_center",
            "tenant_id",
            "status",
            "request_type",
            "created_at",
        ),
        Index(
            "ix_return_requests_platform_updated",
            "tenant_id",
            "shop_id",
            "platform_updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    request_number: Mapped[str] = mapped_column(String(40), nullable=False)
    order_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    platform: Mapped[str | None] = mapped_column(String(32))
    platform_return_id: Mapped[str | None] = mapped_column(String(128))
    platform_status: Mapped[str | None] = mapped_column(String(128))
    platform_reason_text: Mapped[str | None] = mapped_column(Text)
    platform_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    platform_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    refund_currency: Mapped[str | None] = mapped_column(String(3))
    refund_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    raw_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_review"
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True)
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True)
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    items: Mapped[list[ReturnRequestItem]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    order: Mapped[Order] = relationship()
    rma: Mapped[ReturnRma | None] = relationship(
        back_populates="request", cascade="all, delete-orphan", uselist=False
    )


class ReturnRequestItem(TenantScoped, Base):
    __tablename__ = "return_request_items"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_return_request_items_id_tenant"),
        ForeignKeyConstraint(
            ["return_request_id", "tenant_id"],
            ["return_requests.id", "return_requests.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["order_line_id", "tenant_id"],
            ["order_lines.id", "order_lines.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "return_request_id",
            "order_line_id",
            name="uq_return_request_items_request_line",
        ),
        UniqueConstraint(
            "tenant_id",
            "platform_return_line_id",
            name="uq_return_request_items_platform_line",
        ),
        CheckConstraint(
            "requested_quantity > 0", name="ck_return_request_items_quantity"
        ),
        Index("ix_return_request_items_request", "return_request_id"),
        Index("ix_return_request_items_order_line", "order_line_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    return_request_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    order_line_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    platform_return_line_id: Mapped[str | None] = mapped_column(String(128))
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    request: Mapped[ReturnRequest] = relationship(back_populates="items")
    order_line: Mapped[OrderLine] = relationship(viewonly=True)
