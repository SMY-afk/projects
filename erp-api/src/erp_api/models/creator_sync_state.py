from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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


class CreatorSyncState(TenantScoped, Base):
    __tablename__ = "creator_sync_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
            name="fk_creator_sync_states_shop_tenant",
        ),
        ForeignKeyConstraint(
            ["affiliate_creator_id", "tenant_id", "shop_id"],
            [
                "affiliate_creators.id",
                "affiliate_creators.tenant_id",
                "affiliate_creators.shop_id",
            ],
            ondelete="CASCADE",
            name="fk_creator_sync_states_creator_tenant_shop",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "creator_id",
            name="uq_creator_sync_states_creator",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "affiliate_creator_id",
            name="uq_creator_sync_states_affiliate_creator",
        ),
        CheckConstraint(
            "sync_status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_creator_sync_states_status",
        ),
        Index(
            "ix_creator_sync_states_due",
            "tenant_id",
            "shop_id",
            "sync_status",
            "last_sync_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    creator_id: Mapped[str] = mapped_column(String(128), nullable=False)
    affiliate_creator_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_video_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
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
