from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from erp_api import models as registered_models
from erp_api.db.base import Base


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


def _checks(table_name: str) -> str:
    return "\n".join(
        str(constraint.sqltext)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_return_models_are_tenant_safe_and_quantity_checked() -> None:
    assert registered_models.ReturnRequest is not None
    assert {"return_requests", "return_request_items", "return_rmas"} <= (
        Base.metadata.tables.keys()
    )
    assert (
        ("order_id", "tenant_id"),
        ("orders.id", "orders.tenant_id"),
    ) in _foreign_keys("return_requests")
    assert (
        ("order_line_id", "tenant_id"),
        ("order_lines.id", "order_lines.tenant_id"),
    ) in _foreign_keys("return_request_items")
    assert "requested_quantity > 0" in _checks("return_request_items")


def test_rma_is_unique_per_request_and_logistics_task_is_reverse_linked() -> None:
    rma_uniques = {
        tuple(item.columns.keys())
        for item in Base.metadata.tables["return_rmas"].constraints
        if isinstance(item, UniqueConstraint)
    }
    assert ("tenant_id", "return_request_id") in rma_uniques
    assert (
        ("return_rma_id", "tenant_id"),
        ("return_rmas.id", "return_rmas.tenant_id"),
    ) in _foreign_keys("logistics_tasks")
    checks = _checks("logistics_tasks")
    assert "direction IN ('forward', 'reverse')" in checks
    assert "source_type IN ('sales_order', 'return', 'exchange')" in checks
