from __future__ import annotations

from dataclasses import dataclass

from erp_api.services.order_chain_classifier import (
    OrderAttributionDecision,
    OrderChainClassifier,
)
from erp_api.services.tiktok_order_schemas import TikTokOrder


@dataclass(frozen=True)
class OrderSyncMetrics:
    total_orders: int = 0
    confirmed_count: int = 0
    derived_count: int = 0
    unknown_count: int = 0
    unsupported_field_count: int = 0

    def add(self, other: OrderSyncMetrics) -> OrderSyncMetrics:
        return OrderSyncMetrics(
            total_orders=self.total_orders + other.total_orders,
            confirmed_count=self.confirmed_count + other.confirmed_count,
            derived_count=self.derived_count + other.derived_count,
            unknown_count=self.unknown_count + other.unknown_count,
            unsupported_field_count=self.unsupported_field_count
            + other.unsupported_field_count,
        )


def metrics_for_orders(orders: list[TikTokOrder]) -> OrderSyncMetrics:
    metrics = OrderSyncMetrics()
    for order in orders:
        metrics = metrics.add(
            metrics_for_decision(
                OrderChainClassifier.classify(
                    getattr(order, "attribution_signal", None),
                    getattr(order, "affiliate_signal", None),
                    getattr(order, "ads_signal", None),
                    getattr(order, "external_evidence_absence_reason", None),
                )
            )
        )
    return metrics


def metrics_for_decision(decision: OrderAttributionDecision) -> OrderSyncMetrics:
    status_counts = {"confirmed": 0, "derived": 0, "unknown": 0}
    status_counts[
        decision.classification_status
        if decision.classification_status in status_counts
        else "unknown"
    ] = 1
    return OrderSyncMetrics(
        total_orders=1,
        confirmed_count=status_counts["confirmed"],
        derived_count=status_counts["derived"],
        unknown_count=status_counts["unknown"],
        unsupported_field_count=int(decision.evidence.get("strength") == "unsupported"),
    )
