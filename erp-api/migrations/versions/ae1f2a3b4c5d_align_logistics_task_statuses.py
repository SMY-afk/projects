"""align logistics task statuses

Revision ID: ae1f2a3b4c5d
Revises: 9d0e1f2a3b4c
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ae1f2a3b4c5d"
down_revision: str | Sequence[str] | None = "9d0e1f2a3b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_STATUS_CHECK = (
    "status IN ('pending_review', 'pending_pack', 'pending_waybill', "
    "'pending_dispatch', 'shipped', 'in_transit', 'delivered', "
    "'exception', 'cancelled')"
)
OLD_STATUS_CHECK = (
    "status IN ('pending_review', 'reviewed', 'review_exception', "
    "'ready_to_ship', 'shipped', 'cancelled')"
)


def upgrade() -> None:
    op.drop_constraint("ck_logistics_tasks_status", "logistics_tasks", type_="check")
    op.execute(
        sa.text(
            """
            UPDATE logistics_tasks AS task
            SET status = CASE
                WHEN task.status = 'reviewed' THEN 'pending_pack'
                WHEN task.status = 'review_exception' THEN 'exception'
                WHEN task.status = 'ready_to_ship' AND EXISTS (
                    SELECT 1 FROM logistics_packages AS package
                    WHERE package.task_id = task.id
                      AND package.tenant_id = task.tenant_id
                      AND package.status != 'cancelled'
                ) AND NOT EXISTS (
                    SELECT 1 FROM logistics_packages AS package
                    WHERE package.task_id = task.id
                      AND package.tenant_id = task.tenant_id
                      AND package.status NOT IN ('waybill_created', 'shipped', 'cancelled')
                ) THEN 'pending_dispatch'
                WHEN task.status = 'ready_to_ship' THEN 'pending_waybill'
                ELSE task.status
            END
            WHERE task.status IN ('reviewed', 'review_exception', 'ready_to_ship')
            """
        )
    )
    op.create_check_constraint(
        "ck_logistics_tasks_status", "logistics_tasks", NEW_STATUS_CHECK
    )


def downgrade() -> None:
    op.drop_constraint("ck_logistics_tasks_status", "logistics_tasks", type_="check")
    op.execute(
        sa.text(
            """
            UPDATE logistics_tasks
            SET status = CASE
                WHEN status = 'pending_pack' THEN 'reviewed'
                WHEN status IN ('pending_waybill', 'pending_dispatch') THEN 'ready_to_ship'
                WHEN status = 'exception' THEN 'review_exception'
                WHEN status IN ('in_transit', 'delivered') THEN 'shipped'
                ELSE status
            END
            WHERE status IN (
                'pending_pack', 'pending_waybill', 'pending_dispatch',
                'exception', 'in_transit', 'delivered'
            )
            """
        )
    )
    op.create_check_constraint(
        "ck_logistics_tasks_status", "logistics_tasks", OLD_STATUS_CHECK
    )
