from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.role import Role
from erp_api.models.user import User
from erp_api.services.auth import AuthAccount, CurrentUser


class AuthRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def find_account_by_username(self, username: str) -> AuthAccount | None:
        """Authentication is the sole cross-tenant lookup; ambiguity is rejected."""
        async with self._database.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, tenant_id, username, password_hash "
                    "FROM users WHERE username = :username AND status = 'active' LIMIT 2"
                ),
                {"username": username},
            )
            accounts = result.mappings().all()
        if len(accounts) != 1:
            return None
        account = accounts[0]
        return AuthAccount(
            id=account["id"],
            tenant_id=account["tenant_id"],
            username=account["username"],
            password_hash=account["password_hash"],
        )

    async def get_current_user(
        self, user_id: UUID, tenant_id: UUID
    ) -> CurrentUser | None:
        async for session in self._database.session(tenant_id):
            user = await session.scalar(
                select(User)
                .options(selectinload(User.roles).selectinload(Role.permissions))
                .where(User.id == user_id, User.status == "active")
            )
            if not user:
                return None
            roles = [
                {"id": str(role.id), "code": role.code, "name": role.name}
                for role in sorted(user.roles, key=lambda item: item.code)
            ]
            permissions = sorted(
                {
                    permission.code
                    for role in user.roles
                    for permission in role.permissions
                }
            )
            return CurrentUser(
                id=user.id,
                name=user.username,
                username=user.username,
                roles=roles,
                permissions=permissions,
            )
        return None
