from typing import Any

import sqlalchemy as sa


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return tuple(
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    )


def create_package_tables(operations: Any) -> None:
    operations.create_table(
        "logistics_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("package_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("weight_grams", sa.Integer()),
        sa.Column("length_mm", sa.Integer()),
        sa.Column("width_mm", sa.Integer()),
        sa.Column("height_mm", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'packed', 'waybill_created', 'shipped', 'cancelled')",
            name="ck_logistics_packages_status",
        ),
        *(
            sa.CheckConstraint(
                f"{field} IS NULL OR {field} > 0",
                name=f"ck_logistics_packages_{name}",
            )
            for field, name in (
                ("weight_grams", "weight"),
                ("length_mm", "length"),
                ("width_mm", "width"),
                ("height_mm", "height"),
            )
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_logistics_packages_id_tenant"),
        sa.UniqueConstraint(
            "id",
            "task_id",
            "tenant_id",
            name="uq_logistics_packages_id_task_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "package_number",
            name="uq_logistics_packages_tenant_number",
        ),
    )
    operations.create_index(
        "ix_logistics_packages_tenant_id", "logistics_packages", ["tenant_id"]
    )
    operations.create_index(
        "ix_logistics_packages_task_id", "logistics_packages", ["task_id"]
    )
    operations.create_table(
        "logistics_package_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["package_id", "task_id", "tenant_id"],
            [
                "logistics_packages.id",
                "logistics_packages.task_id",
                "logistics_packages.tenant_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_item_id", "task_id", "tenant_id"],
            [
                "logistics_task_items.id",
                "logistics_task_items.task_id",
                "logistics_task_items.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_logistics_package_items_quantity"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "package_id",
            "task_item_id",
            name="uq_logistics_package_items_package_task_item",
        ),
    )
    for column in ("tenant_id", "package_id", "task_id", "task_item_id"):
        operations.create_index(
            f"ix_logistics_package_items_{column}",
            "logistics_package_items",
            [column],
        )
