from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import erp_api.models  # noqa: F401 - register every relationship target before mapper configuration
from erp_api.core.permissions import MODULE_PERMISSION_CODES
from erp_api.models.associations import role_permissions, user_roles
from erp_api.models.permission import Permission
from erp_api.models.role import Role
from erp_api.models.tenant import Tenant
from erp_api.models.user import User
from erp_api.services.auth import hash_password

PERMISSION_NAMES = {
    "orders:view": "查看订单",
    "orders:buyer-pii:view": "查看订单买家隐私信息",
    "products:view": "查看商品",
    "shops:manage": "管理店铺",
    "shops:view": "查看店铺",
    "sync:trigger": "触发同步",
}

PERMISSION_NAMES.update(
    {
        "dashboard:view": "dashboard",
        "sales:view": "sales",
        "ads:view": "ads",
        "platform-warehouse:view": "platform warehouse",
        "warehouse:view": "warehouse",
        "logistics:view": "查看物流",
        "logistics:operate": "操作物流任务",
        "logistics:dispatch": "确认发货",
        "logistics:manage": "管理物流配置",
        "logistics:cost:view": "查看物流费用",
        "logistics:cost:reconcile": "物流费用对账",
        "returns:view": "查看退换货",
        "returns:manage": "管理退换货",
        "returns:inspect": "退换货质检",
        "data:view": "data",
        "bestsellers:view": "bestsellers",
        "affiliate-center:view": "affiliate center",
        "finance:view": "finance",
        "tools:view": "tools",
        "settings:view": "settings",
    }
)


@dataclass(frozen=True)
class BootstrapResult:
    tenant_id: UUID
    user_id: UUID
    tenant_created: bool
    role_created: bool
    user_created: bool
    permissions_created: int


def generate_admin_password(length: int = 24) -> str:
    if length < 12:
        raise ValueError("Generated admin passwords must be at least 12 characters.")
    characters = string.ascii_letters + string.digits
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        *(secrets.choice(characters) for _ in range(length - 3)),
    ]
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def validate_admin_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("The initial admin password must be at least 12 characters.")
    if not any(character.islower() for character in password):
        raise ValueError("The initial admin password must contain a lowercase letter.")
    if not any(character.isupper() for character in password):
        raise ValueError("The initial admin password must contain an uppercase letter.")
    if not any(character.isdigit() for character in password):
        raise ValueError("The initial admin password must contain a digit.")
    return password


async def bootstrap_admin(
    database_url: str,
    *,
    tenant_name: str,
    username: str,
    password: str,
    reset_password: bool = False,
) -> BootstrapResult:
    tenant_name = tenant_name.strip()
    username = username.strip()
    if not tenant_name:
        raise ValueError("The initial tenant name is required.")
    if not username:
        raise ValueError("The initial admin username is required.")
    validate_admin_password(password)

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with session_factory() as session, session.begin():
            tenants = (
                await session.scalars(
                    select(Tenant).where(Tenant.name == tenant_name).limit(2)
                )
            ).all()
            if len(tenants) > 1:
                raise ValueError("Multiple tenants use the requested bootstrap name.")
            tenant_created = not tenants
            tenant = (
                tenants[0]
                if tenants
                else Tenant(id=uuid4(), name=tenant_name, status="active")
            )
            session.add(tenant)

            existing_permissions = {
                permission.code: permission
                for permission in (
                    await session.scalars(
                        select(Permission).where(
                            Permission.code.in_(MODULE_PERMISSION_CODES)
                        )
                    )
                ).all()
            }
            permissions_created = 0
            permissions: list[Permission] = []
            for code in sorted(MODULE_PERMISSION_CODES):
                permission = existing_permissions.get(code)
                if permission is None:
                    permission = Permission(
                        id=uuid4(), code=code, name=PERMISSION_NAMES[code]
                    )
                    session.add(permission)
                    permissions_created += 1
                else:
                    permission.name = PERMISSION_NAMES[code]
                permissions.append(permission)

            role = await session.scalar(
                select(Role).where(Role.tenant_id == tenant.id, Role.code == "admin")
            )
            role_created = role is None
            if role is None:
                role = Role(
                    id=uuid4(), tenant_id=tenant.id, code="admin", name="系统管理员"
                )
                session.add(role)
            else:
                role.name = "系统管理员"

            user = await session.scalar(
                select(User).where(
                    User.tenant_id == tenant.id, User.username == username
                )
            )
            user_created = user is None
            if user is None:
                user = User(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    username=username,
                    password_hash=hash_password(password),
                    status="active",
                )
                session.add(user)
            else:
                user.status = "active"
                if reset_password:
                    user.password_hash = hash_password(password)

            await session.flush()
            await session.execute(
                insert(role_permissions)
                .values(
                    [
                        {"role_id": role.id, "permission_id": permission.id}
                        for permission in permissions
                    ]
                )
                .on_conflict_do_nothing()
            )
            await session.execute(
                insert(user_roles)
                .values(user_id=user.id, role_id=role.id)
                .on_conflict_do_nothing()
            )
        return BootstrapResult(
            tenant_id=tenant.id,
            user_id=user.id,
            tenant_created=tenant_created,
            role_created=role_created,
            user_created=user_created,
            permissions_created=permissions_created,
        )
    finally:
        await engine.dispose()
