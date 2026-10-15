from __future__ import annotations

from decimal import Decimal

from sqlalchemy.dialects import postgresql

from erp_api.services.finance_sync_mapping import _components
from erp_api.services.finance_sync_repository import (
    _minor_units,
    _transaction_upsert_statement,
)


def test_money_conversion_uses_decimal_and_currency_exponent() -> None:
    assert _minor_units(Decimal("12.345"), "USD") == 1235
    assert _minor_units(Decimal("12.5"), "JPY") == 13
    assert _minor_units(Decimal("1.2345"), "KWD") == 1235


def test_settled_transaction_overwrites_estimate_but_not_reverse() -> None:
    statement = _transaction_upsert_statement(
        [
            {
                "tenant_id": "e4408786-af60-545e-8f8c-5ef22a71e675",
                "shop_id": "6dcc40dd-28d8-5dff-b7ec-383e429642f9",
                "source_record_key": "transaction-1",
                "is_estimated": False,
            }
        ]
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT ON CONSTRAINT uq_finance_transactions_tenant_shop_source" in sql
    assert "finance_transactions.is_estimated = true" in sql
    assert "excluded.is_estimated = false" in sql


def test_zero_value_components_are_not_persisted() -> None:
    rows = _components(
        "e4408786-af60-545e-8f8c-5ef22a71e675",
        "6dcc40dd-28d8-5dff-b7ec-383e429642f9",
        "USD",
        "fee_tax",
        {"platform_fee": Decimal("1.25"), "unused_fee": Decimal(0)},
    )

    assert [row["component_code"] for row in rows] == ["platform_fee"]
