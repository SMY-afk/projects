"""add logistics and returns permissions

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "6a7b8c9d0e1f"
down_revision: str | Sequence[str] | None = "5f6a7b8c9d0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION_SPECS = (
    ("logistics:view", "查看物流"),
    ("logistics:operate", "操作物流任务"),
    ("logistics:dispatch", "确认发货"),
    ("logistics:manage", "管理物流配置"),
    ("logistics:cost:view", "查看物流费用"),
    ("logistics:cost:reconcile", "物流费用对账"),
    ("returns:view", "查看退换货"),
    ("returns:manage", "管理退换货"),
    ("returns:inspect", "退换货质检"),
)

ADDED_PERMISSION_CODES = tuple(
    code for code, _name in PERMISSION_SPECS if code != "logistics:view"
)


def _upsert_permission(code: str, name: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, code, name)
            VALUES (:permission_id, :code, :name)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            """
        ).bindparams(
            sa.bindparam("permission_id", value=uuid4(), type_=sa.Uuid()),
            sa.bindparam("code", value=code),
            sa.bindparam("name", value=name),
        )
    )


def _grant_to_admin_roles(code: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
            FROM roles
            CROSS JOIN permissions
            WHERE roles.code = 'admin'
              AND permissions.code = :code
            ON CONFLICT DO NOTHING
            """
        ).bindparams(sa.bindparam("code", value=code))
    )


def upgrade() -> None:
    for code, name in PERMISSION_SPECS:
        _upsert_permission(code, name)
        _grant_to_admin_roles(code)


def downgrade() -> None:
    for code in ADDED_PERMISSION_CODES:
        op.execute(
            sa.text("DELETE FROM permissions WHERE code = :code").bindparams(
                sa.bindparam("code", value=code)
            )
        )
