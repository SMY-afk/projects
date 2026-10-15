from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
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
    from erp_api.models.product_sku import ProductSku
    from erp_api.models.shop import Shop


class Product(TenantScoped, Base):
    __tablename__ = "products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_products_id_tenant"),
        UniqueConstraint(
            "shop_id",
            "platform_product_id",
            name="uq_products_shop_platform_product",
        ),
        Index("ix_products_tenant_shop", "tenant_id", "shop_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    platform_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    category: Mapped[str] = mapped_column(String(200), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    raw_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)

    shop: Mapped[Shop] = relationship(back_populates="products")
    skus: Mapped[list[ProductSku]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        primaryjoin="and_(Product.id == foreign(ProductSku.product_id), "
        "Product.tenant_id == foreign(ProductSku.tenant_id))",
        foreign_keys="[ProductSku.product_id, ProductSku.tenant_id]",
    )
