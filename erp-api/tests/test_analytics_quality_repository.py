from datetime import UTC, datetime

from erp_api.services.analytics_quality_repository import evaluate_page_quality
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


def _item(external_id, source_updated_at, *, amount="10.00", currency="USD"):
    return TikTokAnalyticsItem(
        fields={"externalId": external_id, "gmv": amount, "currency": currency},
        source_status=None,
        status=None,
        source_updated_at=source_updated_at,
    )


def test_quality_checks_keep_appendable_evidence_for_all_required_anomalies() -> None:
    current = datetime(2026, 8, 2, tzinfo=UTC)
    alerts = evaluate_page_quality(
        [
            _item("video-1", None),
            _item("video-1", current, currency="EUR"),
            _item("video-2", current, currency=None),
        ],
        external_id_field="externalId",
        amount_currency_pairs={"gmv": "currency"},
        existing_source_updated_at={"video-1": datetime(2026, 8, 3, tzinfo=UTC)},
    )

    categories = [alert.category for alert in alerts]
    assert "missing_date" in categories
    assert "duplicate_external_id" in categories
    assert "amount_currency_mismatch" in categories
    assert "platform_time_regression" in categories
    assert any(alert.details == {"field": "externalId"} for alert in alerts)
