from uuid import uuid4

from erp_api.services.order_attribution_merger import (
    OrderEvidence,
    merge_order_evidence,
)


def _evidence(**overrides) -> OrderEvidence:
    values = {
        "source_system": "affiliate_order",
        "source_record_key": "record-1",
        "external_conversion_id": "conversion-1",
        "match_key_type": "order_id",
        "match_key_value": "order-1",
        "evidence_strength": "exact_order",
        "confidence_score": 0.9,
        "link_id": uuid4(),
    }
    values.update(overrides)
    return OrderEvidence(**values)


def test_exact_creator_confirms_creator_but_keeps_entry_unknown() -> None:
    decision = merge_order_evidence(
        [_evidence(creator_external_id="creator-1", operator_subject="creator")]
    )

    assert decision.classification_status == "derived"
    assert decision.operator_subject == "creator"
    assert decision.creator_external_id == "creator-1"
    assert decision.entry_point == "unknown"


def test_exact_export_creator_keeps_safe_handle_for_api_display() -> None:
    decision = merge_order_evidence(
        [
            _evidence(
                source_system="seller_order_export",
                creator_external_id="creator-1",
                operator_subject="self_operated",
                evidence={"creator_handle": "pinky__shop4"},
            )
        ]
    )

    assert decision.creator_external_id == "creator-1"
    assert decision.operator_subject == "self_operated"
    assert decision.evidence["creator_handle"] == "pinky__shop4"


def test_exact_video_id_confirms_video_entry() -> None:
    decision = merge_order_evidence(
        [_evidence(video_external_id="video-1", entry_point="video")]
    )

    assert decision.classification_status == "confirmed"
    assert decision.entry_point == "video"
    assert decision.video_external_id == "video-1"


def test_exact_live_or_room_id_confirms_live_entry() -> None:
    decision = merge_order_evidence(
        [_evidence(live_external_id="room-1", entry_point="live")]
    )

    assert decision.classification_status == "confirmed"
    assert decision.entry_point == "live"
    assert decision.live_external_id == "room-1"


def test_product_and_sku_only_do_not_confirm_order_source() -> None:
    decision = merge_order_evidence(
        [_evidence(product_external_id="product-1", sku_external_id="sku-1")]
    )

    assert decision.classification_status == "unknown"
    assert decision.entry_point == "unknown"
    assert decision.product_external_id == "product-1"
    assert decision.sku_external_id == "sku-1"


def test_aggregate_data_is_rejected_even_if_it_contains_product_metrics() -> None:
    decision = merge_order_evidence(
        [
            _evidence(
                evidence_strength="aggregate_only",
                product_external_id="product-1",
                entry_point="video",
            )
        ]
    )

    assert decision.classification_status == "unknown"
    assert decision.evidence["reason"] == "platform_no_order_level_evidence"
    assert decision.evidence_summary == {"evidence_count": 0, "sources": []}


def test_two_strong_content_signals_are_preserved_as_conflict() -> None:
    decision = merge_order_evidence(
        [
            _evidence(video_external_id="video-1", entry_point="video"),
            _evidence(
                source_record_key="record-2",
                external_conversion_id="conversion-2",
                live_external_id="live-1",
                entry_point="live",
            ),
        ]
    )

    assert decision.classification_status == "conflict"
    assert decision.conflict_flags == {"entry_point": ["live", "video"]}
    assert decision.evidence_summary["evidence_count"] == 2


def test_multi_sku_order_keeps_multiple_evidence_rows() -> None:
    decision = merge_order_evidence(
        [
            _evidence(
                order_line_id=uuid4(),
                creator_external_id="creator-1",
                product_external_id="product-1",
                sku_external_id="sku-1",
            ),
            _evidence(
                source_record_key="record-2",
                external_conversion_id="conversion-2",
                order_line_id=uuid4(),
                creator_external_id="creator-1",
                product_external_id="product-2",
                sku_external_id="sku-2",
            ),
        ]
    )

    assert decision.classification_status == "derived"
    assert decision.is_multi_touch is True
    assert decision.evidence_summary["evidence_count"] == 2
    assert decision.evidence_summary["order_line_count"] == 2
    assert decision.evidence_summary["sku_ids"] == ["sku-1", "sku-2"]


def test_weak_exact_line_evidence_does_not_replace_affiliate_creator() -> None:
    decision = merge_order_evidence(
        [
            _evidence(
                creator_external_id="creator-1",
                operator_subject="creator",
            ),
            _evidence(
                source_system="seller_order_list",
                source_record_key="seller-line-1",
                external_conversion_id="seller-line-1",
                match_key_type="order_item_id",
                match_key_value="line-1",
                evidence_strength="exact_order_line",
                confidence_score=0.3,
                order_line_id=uuid4(),
                creator_external_id=None,
                operator_subject=None,
            ),
        ]
    )

    assert decision.creator_external_id == "creator-1"
    assert decision.classification_status == "derived"
    assert decision.is_multi_touch is True
    assert decision.evidence_summary["evidence_count"] == 2
