import pytest

from app.parsers.seller_order_export_parser import (
    SellerOrderExportParseError,
    parse_seller_order_export,
)


def test_export_parser_keeps_only_order_and_creator_fields() -> None:
    payload = (
        "Order ID,Buyer Name,Creator Handle\r\n"
        "941776118773181052\t,Private Buyer,pinky__shop4\r\n"
        "941776118773181052\t,Private Buyer,pinky__shop4\r\n"
        "950129317762695836\t,Another Buyer,\r\n"
    ).encode("utf-8-sig")

    records = parse_seller_order_export(payload)

    assert len(records) == 1
    assert records[0]["main_order_id"] == "941776118773181052"
    assert records[0]["creator_external_id"] is None
    assert records[0]["evidence_json"] == {
        "source": "seller_order_export",
        "field_path": "CSV.Creator Handle",
        "creator_handle": "pinky__shop4",
        "creator_identity_verified": True,
        "reason": "seller_order_export_creator",
    }
    assert "Private Buyer" not in str(records)


def test_export_parser_prefers_direct_creator_id_when_present() -> None:
    payload = (
        b"Order ID,Creator ID,Creator Handle\n"
        b"order-1,9443421243333405023,pinky__shop4\n"
    )

    record = parse_seller_order_export(payload)[0]

    assert record["creator_external_id"] == "9443421243333405023"
    assert record["operator_subject_candidate"] == "creator"
    assert record["confidence_score"] == 0.98


def test_export_parser_rejects_missing_creator_columns() -> None:
    with pytest.raises(SellerOrderExportParseError, match="Creator"):
        parse_seller_order_export(b"Order ID,Buyer Name\norder-1,Private Buyer\n")
