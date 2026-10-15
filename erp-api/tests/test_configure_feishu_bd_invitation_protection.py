import pytest

from scripts.configure_feishu_bd_invitation_protection import (
    TABLE_NAME,
    VIEW_NAME,
    _owner_field_body,
    _table_body,
    _verify_fields,
)


def test_table_body_uses_creator_id_as_primary_field() -> None:
    assert _table_body() == {
        "table": {
            "name": TABLE_NAME,
            "default_view_name": VIEW_NAME,
            "fields": [{"field_name": "达人ID", "type": 1}],
        }
    }


def test_owner_field_is_single_select_with_configured_bds() -> None:
    body = _owner_field_body(("Alice", "Bob"))

    assert body["type"] == 3
    assert [item["name"] for item in body["property"]["options"]] == [
        "Alice",
        "Bob",
    ]


def test_verify_fields_rejects_missing_bd_options() -> None:
    fields = [
        {"field_name": "达人ID", "type": 1, "is_primary": True},
        {
            "field_name": "BD负责人",
            "type": 3,
            "property": {"options": [{"name": "Alice"}]},
        },
    ]

    with pytest.raises(RuntimeError, match="incomplete"):
        _verify_fields(fields, ("Alice", "Bob"))
