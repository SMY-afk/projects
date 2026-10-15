from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import erp_api.models
from erp_api.db.base import Base

LOGISTICS_TABLES = {
    "logistics_tasks",
    "logistics_task_items",
    "logistics_task_operations",
    "logistics_task_reviews",
}
FORBIDDEN_TABLES = {
    "warehouses",
    "warehouse_locations",
    "inventory_balances",
    "inventory_reservations",
    "inventory_movements",
    "transfer_orders",
}
FORBIDDEN_COLUMNS = {
    "warehouse_id",
    "location_id",
    "inventory_id",
    "reserved_quantity",
    "stock_quantity",
}


def _foreign_keys(table_name: str):
    table = Base.metadata.tables[table_name]
    return {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _check_sql(table_name: str) -> str:
    table = Base.metadata.tables[table_name]
    return "\n".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_logistics_models_register_only_the_four_lightweight_tables() -> None:
    assert LOGISTICS_TABLES <= Base.metadata.tables.keys()
    assert FORBIDDEN_TABLES.isdisjoint(Base.metadata.tables)
    assert erp_api.models.LogisticsTask is not None
    assert erp_api.models.LogisticsTaskReview is not None


def test_logistics_task_source_supports_sales_orders_and_future_exchanges_only() -> (
    None
):
    checks = _check_sql("logistics_tasks")
    foreign_keys = _foreign_keys("logistics_tasks")

    assert "sales_order" in checks
    assert "exchange" in checks
    assert "transfer_order" not in checks
    assert (
        ("order_id", "tenant_id"),
        ("orders.id", "orders.tenant_id"),
    ) in foreign_keys


def test_task_items_have_tenant_safe_links_and_positive_quantities() -> None:
    table = Base.metadata.tables["logistics_task_items"]
    foreign_keys = _foreign_keys(table.name)
    unique_constraints = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert (
        ("task_id", "tenant_id"),
        ("logistics_tasks.id", "logistics_tasks.tenant_id"),
    ) in foreign_keys
    assert (
        ("order_line_id", "tenant_id"),
        ("order_lines.id", "order_lines.tenant_id"),
    ) in foreign_keys
    assert (
        "uq_logistics_task_items_tenant_task_source_line",
        ("tenant_id", "task_id", "source_line_id"),
    ) in unique_constraints
    checks = _check_sql(table.name)
    assert "planned_quantity > 0" in checks
    assert "packed_quantity <= planned_quantity" in checks


def test_logistics_tables_do_not_contain_inventory_or_warehouse_fields() -> None:
    for table_name in LOGISTICS_TABLES:
        columns = set(Base.metadata.tables[table_name].columns.keys())
        assert FORBIDDEN_COLUMNS.isdisjoint(columns)


def test_operation_and_review_records_are_task_scoped() -> None:
    for table_name in ("logistics_task_operations", "logistics_task_reviews"):
        assert (
            ("task_id", "tenant_id"),
            ("logistics_tasks.id", "logistics_tasks.tenant_id"),
        ) in _foreign_keys(table_name)
