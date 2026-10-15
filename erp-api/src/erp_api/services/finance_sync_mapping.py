from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from erp_api.services.tiktok_finance_models import (
    FinanceOrderTransaction,
    FinancePayment,
    FinanceStatement,
    FinanceStatementTransaction,
    FinanceUnsettledTransaction,
)

_ZERO_DECIMAL_CURRENCIES = frozenset({"JPY", "KRW", "VND"})
_THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "JOD", "KWD"})


def minor_units(value: Decimal, currency: str) -> int:
    exponent = 0 if currency.upper() in _ZERO_DECIMAL_CURRENCIES else 2
    if currency.upper() in _THREE_DECIMAL_CURRENCIES:
        exponent = 3
    scaled = value * (Decimal(10) ** exponent)
    return int(scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def statement_values(
    tenant_id: UUID, shop_id: UUID, item: FinanceStatement, synced_at: datetime
) -> dict[str, Any]:
    currency = item.currency.upper()
    return {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "platform_statement_id": item.id[:128],
        "status": "available",
        "payment_status": item.payment_status[:32],
        "currency": currency[:3],
        "revenue_amount_minor": minor_units(item.revenue_amount, currency),
        "fee_amount_minor": minor_units(item.fee_amount, currency),
        "adjustment_amount_minor": minor_units(item.adjustment_amount, currency),
        "settlement_amount_minor": minor_units(item.settlement_amount, currency),
        "statement_start_at": item.statement_time,
        "statement_end_at": item.statement_time,
        "platform_created_at": item.statement_time,
        "platform_updated_at": item.payment_time,
        "synced_at": synced_at,
        "source_hash": source_hash(item),
    }


def payment_values(
    tenant_id: UUID, shop_id: UUID, item: FinancePayment, synced_at: datetime
) -> dict[str, Any]:
    currency = item.amount.currency.upper()
    return {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "platform_payment_id": item.id[:128],
        "status": item.status[:32],
        "currency": currency[:3],
        "payment_amount_minor": minor_units(item.amount.value, currency),
        "initiated_at": item.create_time,
        "paid_at": item.paid_time,
        "bank_reference_masked": item.bank_account_masked[:128] or None,
        "platform_updated_at": item.paid_time,
        "synced_at": synced_at,
        "source_hash": source_hash(item),
    }


def settled_transaction_values(
    tenant_id: UUID,
    shop_id: UUID,
    statement_id: UUID,
    item: FinanceStatementTransaction,
    currency: str,
    order_id: UUID | None,
    synced_at: datetime,
) -> dict[str, Any]:
    currency = currency.upper()
    refund = sum(
        value
        for key, value in item.revenue_breakdown.items()
        if "refund" in key.lower()
    )
    return {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "source_record_key": item.id[:256],
        "platform_transaction_id": item.id[:128],
        "statement_id": statement_id,
        "order_id": order_id,
        "platform_order_id": item.order_id[:128] if item.order_id else None,
        "transaction_type": item.type[:64],
        "status": "settled",
        "is_estimated": False,
        "currency": currency[:3],
        "revenue_amount_minor": minor_units(item.revenue_amount, currency),
        "refund_amount_minor": minor_units(refund, currency),
        "shipping_amount_minor": minor_units(item.shipping_cost_amount, currency),
        "fee_amount_minor": minor_units(item.fee_tax_amount, currency),
        "adjustment_amount_minor": minor_units(item.adjustment_amount, currency),
        "settlement_amount_minor": minor_units(item.settlement_amount, currency),
        "occurred_at": item.order_create_time,
        "platform_updated_at": None,
        "synced_at": synced_at,
        "source_hash": source_hash(item),
        "data_completeness": "final",
    }


def unsettled_transaction_values(
    tenant_id: UUID,
    shop_id: UUID,
    item: FinanceUnsettledTransaction,
    order_id: UUID | None,
    synced_at: datetime,
) -> dict[str, Any]:
    currency = item.currency.upper()
    return {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "source_record_key": item.id[:256],
        "platform_transaction_id": item.id[:128],
        "statement_id": None,
        "order_id": order_id,
        "platform_order_id": item.order_id[:128],
        "transaction_type": item.type[:64],
        "status": item.status[:32],
        "is_estimated": True,
        "currency": currency[:3],
        "revenue_amount_minor": minor_units(item.est_revenue_amount, currency),
        "refund_amount_minor": 0,
        "shipping_amount_minor": minor_units(item.est_shipping_cost_amount, currency),
        "fee_amount_minor": minor_units(item.est_fee_tax_amount, currency),
        "adjustment_amount_minor": 0,
        "settlement_amount_minor": minor_units(item.est_settlement_amount, currency),
        "occurred_at": item.order_create_time,
        "platform_updated_at": None,
        "synced_at": synced_at,
        "source_hash": source_hash(item),
        "data_completeness": "estimated",
    }


def component_values(
    tenant_id: UUID,
    transaction_id: UUID,
    item: FinanceStatementTransaction,
    currency: str,
    order_detail: FinanceOrderTransaction | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    groups = (
        ("revenue", item.revenue_breakdown),
        ("fee_tax", item.fee_tax_breakdown),
        ("shipping", item.shipping_cost_breakdown),
        ("supplementary", item.supplementary_component),
    )
    for category, values in groups:
        result.extend(
            _components(tenant_id, transaction_id, currency, category, values)
        )
    if order_detail is not None:
        for sku in order_detail.sku_transactions:
            if sku.settlement_amount == 0:
                continue
            result.append(
                {
                    "tenant_id": tenant_id,
                    "transaction_id": transaction_id,
                    "component_code": "sku_settlement",
                    "component_category": "sku",
                    "amount_minor": minor_units(sku.settlement_amount, currency),
                    "currency": currency[:3],
                    "platform_sku_id": sku.sku_id[:128] or None,
                    "order_line_id": None,
                    "description": (sku.sku_name or sku.product_name)[:1000] or None,
                }
            )
    return result


def source_hash(value: object) -> str:
    payload = asdict(value) if is_dataclass(value) else value
    encoded = json.dumps(
        payload, default=_json_default, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _components(
    tenant_id: UUID,
    transaction_id: UUID,
    currency: str,
    category: str,
    values: Mapping[str, Decimal],
) -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": tenant_id,
            "transaction_id": transaction_id,
            "component_code": code[:128],
            "component_category": category,
            "amount_minor": minor_units(amount, currency),
            "currency": currency[:3],
            "platform_sku_id": None,
            "order_line_id": None,
            "description": None,
        }
        for code, amount in values.items()
        if amount != 0
    ]


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, Decimal, UUID)):
        return str(value)
    raise TypeError(f"Unsupported finance hash value: {type(value).__name__}")
