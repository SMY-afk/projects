import pytest

from scripts.daily_valid_creator_primary_migration import account_copy, comparable_rows


def test_primary_account_copy_preserves_exact_identifiers_and_record_ids():
    rows = [{"record_id": "old", "fields": {"产品线": "童车", "账号名称": " @abc ", "BD负责人": "BD"}}]
    assert account_copy(rows) == [{"record_id": "old", "fields": {"产品线": " @abc "}}]
    migrated = [{"record_id": "old", "fields": {"账号名称": " @abc ", "BD负责人": "BD"}}]
    assert comparable_rows(rows, {"产品线"}) == comparable_rows(migrated, set())


def test_primary_migration_rejects_blank_or_duplicate_record_identity():
    with pytest.raises(ValueError, match="account identity"):
        account_copy([{"record_id": "r", "fields": {"账号名称": ""}}])
    row = {"record_id": "r", "fields": {"账号名称": "abc"}}
    with pytest.raises(ValueError, match="record identity"):
        account_copy([row, row])
