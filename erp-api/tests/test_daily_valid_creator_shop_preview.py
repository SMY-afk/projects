from scripts.daily_valid_creator_sync import preview


def fields(shop):
    return {"账号名称": "abc", "匹配店铺": shop}


def test_two_shop_records_are_not_duplicates():
    desired = {("abc", shop): fields(shop) for shop in ("跨境3", "跨境7")}
    current = [{"record_id": shop, "fields": fields(shop)} for shop in ("跨境3", "跨境7")]
    plan = preview(desired, current)
    assert (plan["updates"], plan["creates"], plan["deduplicates"]) == (0, 0, 0)


def test_same_shop_alias_duplicates_are_detected():
    desired = {("abc", "本土店"): {
        "账号名称": "abc", "匹配店铺": "本土2店",
    }}
    current = [{"record_id": str(index), "fields": {
        "产品线": "遥控车", "账号名称": "abc", "匹配店铺": shop,
    }} for index, shop in enumerate(("本土店", "本土2店"))]
    plan = preview(desired, current)
    assert plan["deduplicates"] == 1


def test_legacy_combined_shop_row_blocks_automatic_write():
    import pytest
    with pytest.raises(ValueError, match="approved scope"):
        preview({}, [{"record_id": "old", "fields": fields("跨境3；跨境7")}])
