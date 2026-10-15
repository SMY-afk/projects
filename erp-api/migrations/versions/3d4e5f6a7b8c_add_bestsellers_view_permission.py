"""add bestsellers view permission

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-08-21
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "3d4e5f6a7b8c"
down_revision: str | Sequence[str] | None = "2c3d4e5f6a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    permission_id = uuid4()
    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, code, name)
            VALUES (:permission_id, 'bestsellers:view', 'bestsellers')
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            """
        ).bindparams(
            sa.bindparam("permission_id", value=permission_id, type_=sa.Uuid())
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
            FROM roles
            CROSS JOIN permissions
            WHERE roles.code = 'admin'
              AND permissions.code = 'bestsellers:view'
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'bestsellers:view'"))
