from scripts.daily_valid_creator_sync import preview


def test_71_authorized_splits_keep_ids_and_use_each_shops_metrics():
    current, desired = [], {}
    for index in range(71):
        account = f"creator{index}"
        current.append({"record_id": f"r{index}", "fields": {"账号名称": account,
            "BD负责人": "BD", "匹配店铺": "跨境3；跨境7", "业绩": 300}})
        for shop, amount in (("跨境3", 100), ("跨境7", 200)):
            desired[(account, shop)] = {"账号名称": account, "BD负责人": "BD",
                "匹配店铺": shop, "业绩": amount, "视频数": 0, "直播数": 0,
                "最近有效日期": None, "同意样品日期": None,
                "保留原因": "有业绩", "数据质量备注": ""}
    plan = preview(desired, current)
    assert (plan["updates"], plan["creates"], plan["deduplicates"], plan["final_count"]) == (71, 71, 0, 142)
    assert plan["operations"]["delete"] == []
    assert len(plan["confirmed_multi_shop_rows"]) == 71
    assert plan["confirmed_multi_shop_rows"][0]["shops"] == ["跨境3", "跨境7"]
    assert all(not record_id.startswith("planned:") for record_id, _ in plan["operations"]["update"])
    assert {row["匹配店铺"] for row in plan["operations"]["create"]} == {"跨境7"}
    assert {row["业绩"] for row in plan["operations"]["create"]} == {200}
    after = [{"record_id": row["record_id"], "fields": {
        **row["fields"], **dict(plan["operations"]["update"])[row["record_id"]]}} for row in current]
    after.extend({"record_id": f"new{index}", "fields": fields}
        for index, fields in enumerate(plan["operations"]["create"]))
    second = preview(desired, after)
    assert (second["updates"], second["creates"], second["deduplicates"]) == (0, 0, 0)


def test_unscoped_historical_duplicates_are_preserved_without_deletion():
    current = [{"record_id": record_id, "fields": {"账号名称": "abc",
        "BD负责人": "BD", "同意样品日期": day}}
        for record_id, day in (("old", "2026-08-01"), ("new", "2026-10-13"))]
    desired = {("abc", ""): {"账号名称": "abc", "BD负责人": "BD",
        "同意样品日期": "2026-10-13"}}
    plan = preview(desired, current)
    assert plan["operations"]["delete"] == []
    assert plan["retained_unscoped_ids"] == ["old"]
    assert plan["final_count"] == 2


def test_mamakailashops_reuses_existing_newer_row_and_keeps_older_history():
    current = [{"record_id": record_id, "fields": {"账号名称": "mamakailashops",
        "BD负责人": "帝维", "同意样品日期": day}}
        for record_id, day in (("old", "2026-08-20"), ("new", "2026-08-21"))]
    desired = {("mamakailashops", "跨境12"): {"账号名称": "mamakailashops",
        "BD负责人": "帝维", "同意样品日期": "2026-08-21", "匹配店铺": "跨境12"}}
    plan = preview(desired, current)
    assert (plan["creates"], plan["deduplicates"]) == (0, 0)
    assert plan["final_count"] == 2
    assert plan["operations"]["delete"] == []
    assert dict(plan["operations"]["update"])["new"]["匹配店铺"] == "跨境12"
    assert "old" not in dict(plan["operations"]["update"])
