from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
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
    from erp_api.models.product import Product


class ProductSku(TenantScoped, Base):
    __tablename__ = "product_skus"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
        ),
        UniqueConstraint("id", "tenant_id", name="uq_product_skus_id_tenant"),
        UniqueConstraint(
            "product_id",
            "platform_sku_id",
            name="uq_product_skus_product_platform_sku",
        ),
        Index("ix_product_skus_tenant_product", "tenant_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    product_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform_sku_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped[Product] = relationship(
        back_populates="skus",
        primaryjoin="and_(Product.id == foreign(ProductSku.product_id), "
        "Product.tenant_id == foreign(ProductSku.tenant_id))",
        foreign_keys="[ProductSku.product_id, ProductSku.tenant_id]",
    )
