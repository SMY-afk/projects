from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.order import Order


class OrderLine(TenantScoped, Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_order_lines_id_tenant"),
        UniqueConstraint(
            "order_id", "platform_line_id", name="uq_order_lines_order_platform_line"
        ),
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
        ),
        ForeignKeyConstraint(
            ["product_sku_id", "tenant_id"],
            ["product_skus.id", "product_skus.tenant_id"],
        ),
        Index("ix_order_lines_tenant_order", "tenant_id", "order_id"),
        Index("ix_order_lines_tenant_product", "tenant_id", "product_id"),
        Index("ix_order_lines_tenant_product_sku", "tenant_id", "product_sku_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    order_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    product_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
    )
    product_sku_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("product_skus.id", ondelete="SET NULL"),
        index=True,
    )
    platform_line_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform_product_id: Mapped[str | None] = mapped_column(String(128))
    platform_sku_id: Mapped[str | None] = mapped_column(String(128), index=True)
    seller_sku: Mapped[str | None] = mapped_column(String(128))
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    sku_name: Mapped[str | None] = mapped_column(String(300))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    original_unit_price_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    sale_unit_price_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    discount_amount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    line_total_amount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    order: Mapped[Order] = relationship(back_populates="lines")
