from scripts.daily_valid_creator_recovery import expected_recovery_fields


def test_new_record_is_not_looked_up_in_old_backup_or_modified():
    before = {"账号名称": "new", "BD负责人": "BD"}
    assert expected_recovery_fields("new", before, {}, set()) == before


def test_only_three_fields_are_restored_for_explicit_original_record():
    before = {"账号名称": "abc", "BD负责人": "BD", "匹配店铺": "",
        "数据质量备注": "bad", "最新更新时间": 2, "业绩": 12}
    old = {"old": {"匹配店铺": "跨境3；跨境7", "数据质量备注": "original", "最新更新时间": 1}}
    expected = expected_recovery_fields("old", before, old, {"old"})
    assert expected == {**before, **old["old"]}
