from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class FinanceTransaction(TenantScoped, Base):
    __tablename__ = "finance_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["statement_id", "tenant_id"],
            ["finance_statements.id", "finance_statements.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_finance_transactions_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "source_record_key",
            name="uq_finance_transactions_tenant_shop_source",
        ),
        Index(
            "ix_finance_transactions_filter",
            "tenant_id",
            "shop_id",
            "occurred_at",
            "currency",
            "status",
        ),
        Index(
            "ix_finance_transactions_statement",
            "tenant_id",
            "statement_id",
        ),
        Index("ix_finance_transactions_order", "tenant_id", "order_id"),
        Index(
            "ix_finance_transactions_platform_order",
            "tenant_id",
            "shop_id",
            "platform_order_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(256), nullable=False)
    platform_transaction_id: Mapped[str | None] = mapped_column(String(128))
    statement_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    order_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    platform_order_id: Mapped[str | None] = mapped_column(String(128))
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    revenue_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refund_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shipping_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    platform_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_completeness: Mapped[str] = mapped_column(String(32), nullable=False)
