from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index, String, Text
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class FinanceTransactionComponent(TenantScoped, Base):
    __tablename__ = "finance_transaction_components"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id", "tenant_id"],
            ["finance_transactions.id", "finance_transactions.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["order_line_id", "tenant_id"],
            ["order_lines.id", "order_lines.tenant_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_finance_components_transaction",
            "tenant_id",
            "transaction_id",
            "component_category",
        ),
        Index(
            "ix_finance_components_code",
            "tenant_id",
            "component_code",
        ),
        Index(
            "ix_finance_components_platform_sku",
            "tenant_id",
            "platform_sku_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    transaction_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    component_code: Mapped[str] = mapped_column(String(128), nullable=False)
    component_category: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    platform_sku_id: Mapped[str | None] = mapped_column(String(128))
    order_line_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    description: Mapped[str | None] = mapped_column(Text)
