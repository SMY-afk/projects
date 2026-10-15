import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.parsers.scraped_data_parser import (
    AFFILIATE_DATA_TYPE,
    ScrapedDataParseError,
    parse_scraped_data_item,
    parse_scraped_data_response,
)
from erp_api.models.scraped_data import ScrapedData

FIXTURE_PATH = Path("backend/tests/data/affiliate_test.json")


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8-sig"))


def test_real_affiliate_fixture_produces_50_unique_scraped_records() -> None:
    payload = _payload()

    parsed = parse_scraped_data_response(payload)

    assert len(parsed) == 50
    platform_ids = [item["platform_id"] for item in parsed]
    assert len(set(platform_ids)) == 50
    assert all(
        str(value).startswith(f"{AFFILIATE_DATA_TYPE}:") for value in platform_ids
    )
    assert all(len(str(value)) <= 100 for value in platform_ids)


def test_real_affiliate_item_maps_search_fields_and_preserves_raw_json() -> None:
    payload = _payload()
    raw_item = payload["data"]["sku_order_list"][0]  # type: ignore[index]

    parsed = parse_scraped_data_item(raw_item)  # type: ignore[arg-type]

    base = raw_item["sku_order_base_info_for_affiliate_seller"]
    sku_order = base["sku_order_info"]
    creator = base["creator_info"]
    product = base["product_info"]
    assert parsed["platform_id"] == (
        f"affiliate_order:{sku_order['main_order_id']}:{sku_order['sku_id']}"
    )
    assert parsed["data_type"] == "affiliate_order"
    assert parsed["creator_id"] == creator["creator_id"]
    assert parsed["creator_name"] == creator["creator_nickname"]
    assert parsed["title"] == product["product_name"]
    assert parsed["raw_data"] == raw_item
    json.dumps(parsed["raw_data"], ensure_ascii=False)


def test_parser_does_not_mutate_captured_payload() -> None:
    payload = _payload()
    original = deepcopy(payload)

    parse_scraped_data_response(payload)

    assert payload == original


def test_parser_output_can_construct_scraped_data_model() -> None:
    parsed = parse_scraped_data_response(_payload())[0]

    model = ScrapedData(**parsed)

    assert model.platform_id == parsed["platform_id"]
    assert model.data_type == "affiliate_order"
    assert model.raw_data == parsed["raw_data"]


def test_parser_rejects_non_success_response() -> None:
    with pytest.raises(ScrapedDataParseError, match="code is not zero"):
        parse_scraped_data_response({"code": 10001, "data": {}})


def test_parser_reports_invalid_item_index_and_missing_natural_key() -> None:
    payload = {
        "code": 0,
        "data": {
            "sku_order_list": [
                {
                    "sku_order_base_info_for_affiliate_seller": {
                        "sku_order_info": {"main_order_id": "main-1"}
                    }
                }
            ]
        },
    }

    with pytest.raises(
        ScrapedDataParseError,
        match=r"sku_order_list\[0\].*sku_id is required",
    ):
        parse_scraped_data_response(payload)
