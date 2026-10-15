from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.affiliate_order_item import AffiliateOrderItem
    from erp_api.models.affiliate_sync_state import AffiliateSyncState
    from erp_api.models.order import Order
    from erp_api.models.product import Product
    from erp_api.models.product_sync_run import ProductSyncRun
    from erp_api.models.shop_connection import ShopConnection
    from erp_api.models.tenant import Tenant


class Shop(TenantScoped, Base):
    __tablename__ = "shops"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_shops_id_tenant"),
        UniqueConstraint(
            "platform", "platform_shop_id", name="uq_shops_platform_external_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "platform",
            "platform_shop_id",
            name="uq_shops_tenant_platform_external_id",
        ),
        Index("ix_shops_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    platform_shop_id: Mapped[str] = mapped_column(String(100), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    shop_code: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(30))
    timezone: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tenant: Mapped[Tenant] = relationship(back_populates="shops")
    connection: Mapped[ShopConnection | None] = relationship(
        back_populates="shop",
        cascade="all, delete-orphan",
        uselist=False,
    )
    products: Mapped[list[Product]] = relationship(
        back_populates="shop",
        cascade="all, delete-orphan",
    )
    product_sync_runs: Mapped[list[ProductSyncRun]] = relationship(
        back_populates="shop",
        cascade="all, delete-orphan",
    )
    orders: Mapped[list[Order]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    affiliate_order_items: Mapped[list[AffiliateOrderItem]] = relationship(
        back_populates="shop",
        cascade="all, delete-orphan",
    )
    affiliate_sync_state: Mapped[AffiliateSyncState | None] = relationship(
        back_populates="shop",
        cascade="all, delete-orphan",
        uselist=False,
    )
