import json
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

from erp_api.services.order_chain_classifier import (
    OrderAttributionDecision,
    OrderChainClassifier,
)
from erp_api.services.tiktok_ads_order_schemas import TikTokAdsOrderSignal
from erp_api.services.tiktok_affiliate_order_schemas import TikTokAffiliateOrderSignal
from erp_api.services.tiktok_order_schemas import (
    TikTokOrderAttributionSignal,
    parse_order_detail_response,
    parse_order_page_response,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tiktok_order_attribution"


def _fixtures() -> list[dict[str, Any]]:
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if "name" in fixture:
            fixtures.append(fixture)
    return fixtures


def test_redacted_chain_fixtures_never_guess_unsupported_routes() -> None:
    fixtures = _fixtures()

    assert {item["name"] for item in fixtures} == {
        "organic_creator_video",
        "paid_creator_video",
        "paid_self_operated_live",
        "organic_mall_search_recommendation",
        "organic_creator_offsite",
        "organic_creator_showcase",
        "organic_creator_affiliate_product_page",
        "sample_candidate",
        "purchase_sample_rebate",
        "conflicting_signals",
        "missing_fields",
        "unknown_enum",
    }

    for fixture in fixtures:
        order = parse_order_page_response(
            {"data": {"orders": [fixture["order"]]}}
        ).orders[0]
        decision = OrderChainClassifier.classify(order.attribution_signal)
        expected = fixture["expected"]

        assert decision.chain_code == expected["chain_code"], fixture["name"]
        assert decision.classification_status == expected["classification_status"], (
            fixture["name"]
        )
        if "signal_value" in expected:
            assert decision.evidence["value"] == expected["signal_value"], fixture[
                "name"
            ]
        assert decision.traffic_source == "unknown", fixture["name"]
        assert decision.operator_subject == "unknown", fixture["name"]
        assert decision.entry_point == "unknown", fixture["name"]


def test_fixture_platform_candidates_do_not_expand_confirmed_signal_dto() -> None:
    fixture = next(item for item in _fixtures() if item["name"] == "unknown_enum")
    order = parse_order_page_response({"data": {"orders": [fixture["order"]]}}).orders[
        0
    ]

    assert asdict(order.attribution_signal) == {
        "is_sample_order": None,
        "source_updated_at": datetime.fromtimestamp(1_760_000_111, tz=UTC),
    }


def test_all_chain_fixtures_are_accepted_by_order_detail_parser() -> None:
    for fixture in _fixtures():
        order = parse_order_detail_response({"data": {"orders": [fixture["order"]]}})

        assert order.platform_order_id == fixture["order"]["id"]
        assert order.attribution_signal is not None


def test_unsupported_conflict_candidates_are_not_treated_as_winning_evidence() -> None:
    fixture = next(
        item for item in _fixtures() if item["name"] == "conflicting_signals"
    )
    order = parse_order_page_response({"data": {"orders": [fixture["order"]]}}).orders[
        0
    ]
    decision = OrderChainClassifier.classify(order.attribution_signal)

    # The conflicting source/operator/entry fields are not step-0-confirmed
    # fields, so they are discarded before classification rather than resolved.
    assert decision.chain_code == "unknown"
    assert decision.classification_status == "unknown"
    assert decision.evidence["reason"] == "missing_platform_field"


def test_every_normal_chain_combination_has_an_unknown_fixture_expectation() -> None:
    catalog = json.loads(
        (FIXTURE_DIR / "normal_chain_catalog.json").read_text(encoding="utf-8")
    )

    combinations = list(
        product(
            catalog["traffic_sources"],
            catalog["operator_subjects"],
            catalog["entry_points"],
        )
    )

    assert len(combinations) == 36
    for traffic_source, operator_subject, entry_point in combinations:
        fixture = {
            "id": f"catalog-{traffic_source}-{operator_subject}-{entry_point}",
            "status": "AWAITING_SHIPMENT",
            "create_time": 1_760_000_000,
            "update_time": 1_760_000_200,
            "is_sample_order": False,
            "traffic_source_code": traffic_source,
            "operator_subject_code": operator_subject,
            "entry_point_code": entry_point,
            "line_items": [],
        }
        order = parse_order_page_response({"data": {"orders": [fixture]}}).orders[0]
        decision = OrderChainClassifier.classify(order.attribution_signal)

        assert decision.chain_code == catalog["expected_chain_code"]
        assert (
            decision.classification_status == catalog["expected_classification_status"]
        )
        assert decision.traffic_source == "unknown"
        assert decision.operator_subject == "unknown"
        assert decision.entry_point == "unknown"


def test_classifier_keeps_sample_candidate_without_guessing_subtype_or_chain() -> None:
    updated_at = datetime(2026, 8, 13, 2, 45, 49, tzinfo=UTC)
    signal = TikTokOrderAttributionSignal(
        is_sample_order=True, source_updated_at=updated_at
    )

    decision = OrderChainClassifier.classify(signal)

    assert decision == OrderAttributionDecision(
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="shop_order_detail",
        evidence={
            "source": "shop_order_detail",
            "field_path": "data.orders[].is_sample_order",
            "value": "true",
            "strength": "medium",
            "reason": "missing_platform_field",
        },
        source_updated_at=updated_at,
    )


def test_false_sample_signal_does_not_prove_normal_or_organic() -> None:
    decision = OrderChainClassifier().classify(
        TikTokOrderAttributionSignal(is_sample_order=False)
    )

    assert decision.chain_code == "unknown"
    assert decision.special_order_type == "unknown"
    assert decision.traffic_source == "unknown"
    assert decision.classification_status == "unknown"
    assert decision.evidence["value"] == "false"
    assert decision.evidence["strength"] == "medium"


def test_missing_signal_returns_unknown_decision_without_failing() -> None:
    decision = OrderChainClassifier.classify(None)

    assert decision.chain_code == "unknown"
    assert decision.classification_method == "shop_order_detail"
    assert decision.source_updated_at is None
    assert decision.evidence == {
        "source": "shop_order_detail",
        "field_path": "data.orders[].is_sample_order",
        "value": "missing",
        "strength": "unsupported",
        "reason": "missing_platform_field",
    }


def test_classifier_does_not_mutate_signal_and_returns_fresh_evidence() -> None:
    signal = TikTokOrderAttributionSignal(is_sample_order=None)

    first = OrderChainClassifier.classify(signal)
    second = OrderChainClassifier.classify(signal)

    assert signal.is_sample_order is None
    assert first.evidence == second.evidence
    assert first.evidence is not second.evidence


def test_exact_affiliate_evidence_classifies_creator_order_and_preserves_ids() -> None:
    decision = OrderChainClassifier.classify(
        None,
        TikTokAffiliateOrderSignal(
            external_conversion_id="conversion-1",
            match_key_type="order_item_id",
            match_key="item-1",
            creator_external_id="creator-1",
            traffic_source="organic",
            entry_point="affiliate_product_page",
            platform_source_code="creator_affiliate",
        ),
    )
    assert decision.classification_method == "affiliate_order"
    assert decision.classification_status == "confirmed"
    assert decision.chain_code == "organic.creator.affiliate_product_page"
    assert decision.creator_external_id == "creator-1"
    assert decision.platform_source_code == "creator_affiliate"


def test_affiliate_creator_evidence_is_derived_with_unknown_entry_point() -> None:
    decision = OrderChainClassifier.classify(
        None,
        TikTokAffiliateOrderSignal(
            external_conversion_id="conversion-1",
            match_key_type="order_id",
            match_key="order-1",
            creator_external_id="creator-1",
        ),
    )
    assert decision.classification_method == "affiliate_order"
    assert decision.classification_status == "derived"
    assert decision.operator_subject == "creator"
    assert decision.traffic_source == "unknown"
    assert decision.entry_point == "unknown"
    assert decision.chain_code == "unknown"


def test_affiliate_unknown_enum_values_are_not_persisted_as_new_dimensions() -> None:
    decision = OrderChainClassifier.classify(
        None,
        TikTokAffiliateOrderSignal(
            external_conversion_id="conversion-1",
            match_key_type="order_id",
            match_key="order-1",
            creator_external_id="creator-1",
            traffic_source="mystery_source",
            operator_subject="mystery_operator",
            entry_point="mystery_entry",
        ),
    )
    assert decision.traffic_source == "unknown"
    assert decision.operator_subject == "unknown"
    assert decision.entry_point == "unknown"
    assert decision.chain_code == "unknown"


def test_exact_ads_order_evidence_uses_ads_order_link_and_campaign_id() -> None:
    decision = OrderChainClassifier.classify(
        None,
        ads_signal=TikTokAdsOrderSignal(
            external_conversion_id="ads-conversion-1",
            match_key_type="order_id",
            match_key="order-1",
            campaign_external_id="campaign-1",
            traffic_source="paid_ads",
            operator_subject="self_operated",
            entry_point="live",
        ),
    )
    assert decision.classification_method == "ads_order_link"
    assert decision.classification_status == "derived"
    assert decision.chain_code == "paid_ads.self_operated.live"
    assert decision.campaign_external_id == "campaign-1"


def test_ads_aggregate_without_order_key_is_ignored() -> None:
    from erp_api.services.tiktok_ads_order_client import parse_ads_order_response

    assert (
        parse_ads_order_response(
            {
                "data": {
                    "conversions": [
                        {"campaign_id": "campaign-1", "conversion_id": "conversion-1"}
                    ]
                }
            }
        )
        == []
    )


def test_conflicting_affiliate_and_ads_links_stay_unknown() -> None:
    affiliate = TikTokAffiliateOrderSignal(
        external_conversion_id="affiliate-1",
        match_key_type="order_id",
        match_key="order-1",
        creator_external_id="creator-1",
        traffic_source="organic",
        entry_point="video",
    )
    ads = TikTokAdsOrderSignal(
        external_conversion_id="ads-1",
        match_key_type="order_id",
        match_key="order-1",
        traffic_source="paid_ads",
        entry_point="live",
    )
    decision = OrderChainClassifier.classify(None, affiliate, ads)
    assert decision.classification_status == "unknown"
    assert decision.classification_method == "shop_order_detail"
    assert decision.evidence["reason"] == "conflicting_signals"


def test_missing_external_order_key_is_unknown_with_explicit_reason() -> None:
    from erp_api.services.external_order_evidence import (
        PLATFORM_NO_ORDER_LEVEL_EVIDENCE,
    )

    decision = OrderChainClassifier.classify(
        None, external_evidence_absence_reason=PLATFORM_NO_ORDER_LEVEL_EVIDENCE
    )
    assert decision.classification_status == "unknown"
    assert decision.evidence["reason"] == PLATFORM_NO_ORDER_LEVEL_EVIDENCE
    assert decision.evidence["value"] == "missing_order_level_key"


def test_unconfigured_external_evidence_endpoint_is_unknown_with_explicit_reason() -> (
    None
):
    from erp_api.services.external_order_evidence import UNSUPPORTED_ENDPOINT

    decision = OrderChainClassifier.classify(
        TikTokOrderAttributionSignal(is_sample_order=False),
        external_evidence_absence_reason=UNSUPPORTED_ENDPOINT,
    )

    assert decision.classification_status == "unknown"
    assert decision.evidence["reason"] == UNSUPPORTED_ENDPOINT
    assert decision.evidence["strength"] == "unsupported"
