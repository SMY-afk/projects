from app.parsers.seller_order_export_parser import parse_seller_order_export
from erp_api.services.seller_evidence_sync_repository import (
    _enrich_export_records,
    _extract_creator_accounts,
)


def test_export_handle_maps_to_known_self_operated_creator_id() -> None:
    accounts = _extract_creator_accounts(
        [
            {
                "data": {
                    "stats": [
                        {
                            "creator_meta": {
                                "id": "9443421243333405023",
                                "handle": "pinky__shop4",
                                "alias": "pinky66_shop",
                                "type": 2,
                            }
                        }
                    ]
                }
            }
        ]
    )
    records = parse_seller_order_export(
        b"Order ID,Creator Handle\norder-1,pinky__shop4\n"
    )

    enriched = _enrich_export_records(records, accounts)

    assert enriched[0]["creator_external_id"] == "9443421243333405023"
    assert enriched[0]["operator_subject_candidate"] == "self_operated"
    assert enriched[0]["confidence_score"] == 0.98
    assert enriched[0]["source_system"] == "seller_managed_creator_export"
    assert enriched[0]["evidence_json"]["creator_alias"] == "pinky66_shop"
    assert enriched[0]["evidence_json"]["creator_account_type"] == "marketing"


def test_unknown_export_handle_is_not_written_into_creator_id() -> None:
    records = parse_seller_order_export(
        b"Order ID,Creator Handle\norder-1,external_creator\n"
    )

    enriched = _enrich_export_records(records, {})

    assert enriched == []
