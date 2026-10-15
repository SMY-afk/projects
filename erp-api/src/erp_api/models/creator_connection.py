from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class CreatorConnection(TenantScoped, Base):
    __tablename__ = "creator_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "platform",
            "open_id",
            name="uq_creator_connections_tenant_platform_open_id",
        ),
        CheckConstraint("user_type = 1", name="ck_creator_connections_user_type"),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    authorized_by_user_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(30), nullable=False, default="tiktok")
    open_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_type: Mapped[int] = mapped_column(nullable=False, default=1)
    region: Mapped[str | None] = mapped_column(String(30))
    auth_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="authorized"
    )
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
