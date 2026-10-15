from datetime import UTC, datetime

from erp_api.services.order_chain_classifier import OrderAttributionDecision
from erp_api.services.order_sync_metrics import metrics_for_decision


def _decision(status: str, *, strength: str = "medium") -> OrderAttributionDecision:
    return OrderAttributionDecision(
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status=status,
        classification_method="shop_order_detail",
        evidence={"strength": strength},
        source_updated_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def test_metrics_count_each_classification_status_once() -> None:
    assert metrics_for_decision(_decision("confirmed")).confirmed_count == 1
    assert metrics_for_decision(_decision("derived")).derived_count == 1
    assert metrics_for_decision(_decision("unknown")).unknown_count == 1


def test_metrics_count_unsupported_platform_evidence() -> None:
    metrics = metrics_for_decision(_decision("unknown", strength="unsupported"))

    assert metrics.total_orders == 1
    assert metrics.unknown_count == 1
    assert metrics.unsupported_field_count == 1


def test_metrics_count_unconfigured_external_evidence_as_unsupported() -> None:
    metrics = metrics_for_decision(_decision("unknown", strength="unsupported"))

    assert metrics.unsupported_field_count == 1
