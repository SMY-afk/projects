from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

import erp_api.models
from erp_api.db.base import Base

FINANCE_TABLES = {
    "finance_statements",
    "finance_payments",
    "finance_payment_statements",
    "finance_transactions",
    "finance_transaction_components",
    "finance_sync_runs",
    "finance_sync_cursors",
}


def _unique_constraints(table_name: str) -> set[tuple[str | None, tuple[str, ...]]]:
    table = Base.metadata.tables[table_name]
    return {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_keys(
    table_name: str,
) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    table = Base.metadata.tables[table_name]
    return {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _indexes(table_name: str) -> dict[str | None, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {index.name: tuple(index.columns.keys()) for index in table.indexes}


def test_finance_models_register_all_seven_physical_tables() -> None:
    assert FINANCE_TABLES.issubset(Base.metadata.tables)
    assert erp_api.models.FinanceStatement is not None
    assert erp_api.models.FinanceSyncCursor is not None


def test_finance_statements_and_payments_are_shop_scoped_and_idempotent() -> None:
    for table_name, unique_name, external_id in (
        (
            "finance_statements",
            "uq_finance_statements_tenant_shop_platform",
            "platform_statement_id",
        ),
        (
            "finance_payments",
            "uq_finance_payments_tenant_shop_platform",
            "platform_payment_id",
        ),
    ):
        assert (
            unique_name,
            ("tenant_id", "shop_id", external_id),
        ) in _unique_constraints(table_name)
        assert (
            ("shop_id", "tenant_id"),
            ("shops.id", "shops.tenant_id"),
        ) in _foreign_keys(table_name)


def test_payment_statement_bridge_cannot_cross_tenant_boundaries() -> None:
    table = Base.metadata.tables["finance_payment_statements"]

    assert tuple(table.primary_key.columns.keys()) == (
        "tenant_id",
        "payment_id",
        "statement_id",
    )
    assert (
        ("payment_id", "tenant_id"),
        ("finance_payments.id", "finance_payments.tenant_id"),
    ) in _foreign_keys(table.name)
    assert (
        ("statement_id", "tenant_id"),
        ("finance_statements.id", "finance_statements.tenant_id"),
    ) in _foreign_keys(table.name)


def test_transactions_use_tenant_safe_optional_links_and_source_identity() -> None:
    assert (
        "uq_finance_transactions_tenant_shop_source",
        ("tenant_id", "shop_id", "source_record_key"),
    ) in _unique_constraints("finance_transactions")
    foreign_keys = _foreign_keys("finance_transactions")
    assert (
        ("statement_id", "tenant_id"),
        ("finance_statements.id", "finance_statements.tenant_id"),
    ) in foreign_keys
    assert (
        ("order_id", "tenant_id"),
        ("orders.id", "orders.tenant_id"),
    ) in foreign_keys
    assert Base.metadata.tables["finance_transactions"].c.statement_id.nullable
    assert Base.metadata.tables["finance_transactions"].c.order_id.nullable


def test_components_preserve_unknown_codes_and_tenant_safe_links() -> None:
    table = Base.metadata.tables["finance_transaction_components"]
    foreign_keys = _foreign_keys(table.name)

    assert (
        ("transaction_id", "tenant_id"),
        ("finance_transactions.id", "finance_transactions.tenant_id"),
    ) in foreign_keys
    assert (
        ("order_line_id", "tenant_id"),
        ("order_lines.id", "order_lines.tenant_id"),
    ) in foreign_keys
    assert table.c.component_code.nullable is False
    assert table.c.component_category.nullable is False


def test_finance_sync_models_have_cursor_identity_and_operational_indexes() -> None:
    assert (
        "uq_finance_sync_cursors_tenant_shop_entity",
        ("tenant_id", "shop_id", "entity_type"),
    ) in _unique_constraints("finance_sync_cursors")

    statement_indexes = _indexes("finance_statements")
    payment_indexes = _indexes("finance_payments")
    transaction_indexes = _indexes("finance_transactions")
    sync_indexes = _indexes("finance_sync_runs")
    assert statement_indexes["ix_finance_statements_filter"] == (
        "tenant_id",
        "shop_id",
        "statement_end_at",
        "currency",
        "payment_status",
    )
    assert payment_indexes["ix_finance_payments_filter"] == (
        "tenant_id",
        "shop_id",
        "paid_at",
        "currency",
        "status",
    )
    assert transaction_indexes["ix_finance_transactions_filter"] == (
        "tenant_id",
        "shop_id",
        "occurred_at",
        "currency",
        "status",
    )
    assert sync_indexes["ix_finance_sync_runs_window"] == (
        "tenant_id",
        "shop_id",
        "entity_type",
        "window_from",
        "window_to",
        "status",
    )


def test_payment_schema_never_stores_a_raw_bank_account() -> None:
    columns = Base.metadata.tables["finance_payments"].columns

    assert "bank_reference_masked" in columns
    assert "bank_account" not in columns
    assert "bank_account_ciphertext" not in columns
