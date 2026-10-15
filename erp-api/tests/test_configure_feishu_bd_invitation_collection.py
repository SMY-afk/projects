import pytest

from scripts.configure_feishu_bd_invitation_collection import (
    _owner_field_body,
    _planned_actions,
    _verify_fields,
)


def _default_fields():
    return [
        {"field_id": "fld-auto", "field_name": "自动编号", "type": 1005},
        {"field_id": "fld-text", "field_name": "文本", "type": 1},
        {
            "field_id": "fld-select",
            "field_name": "单选",
            "type": 3,
            "property": {"options": []},
        },
        {"field_id": "fld-time", "field_name": "提交时间", "type": 1001},
        {"field_id": "fld-user", "field_name": "提交人", "type": 1003},
    ]


def test_collection_plan_renames_default_questions_and_replaces_options() -> None:
    assert _planned_actions(_default_fields(), ("Alice", "Bob")) == [
        "rename:文本->达人ID",
        "rename:单选->BD负责人",
        "replace-bd-options",
        "create:备注",
    ]


def test_owner_field_uses_all_configured_bds() -> None:
    body = _owner_field_body(("Alice", "Bob"))

    assert body["field_name"] == "BD负责人"
    assert [item["name"] for item in body["property"]["options"]] == [
        "Alice",
        "Bob",
    ]


def test_collection_verify_rejects_incomplete_bd_options() -> None:
    fields = _default_fields()
    fields[1]["field_name"] = "达人ID"
    fields[2]["field_name"] = "BD负责人"
    fields[2]["property"]["options"] = [{"name": "Alice"}]
    fields.append({"field_id": "fld-remark", "field_name": "备注", "type": 1})

    with pytest.raises(RuntimeError, match="options"):
        _verify_fields(fields, ("Alice", "Bob"))
