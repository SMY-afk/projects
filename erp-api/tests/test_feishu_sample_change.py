from datetime import UTC, datetime

import pytest

from erp_api.services.feishu_sample_change import (
    filter_feishu_business_fields,
    parse_feishu_sample_change,
)


def test_parse_feishu_sample_change_extracts_actor_and_business_fields() -> None:
    result = parse_feishu_sample_change(
        {
            "最后修改人": {"id": "ou_user", "name": "Test User"},
            "最后修改时间": 1788946000000,
            "分配BD": "BD A",
            "处理状态": "跟进中",
            "处理结果": "Accepted",
            "备注": "Note",
            "TK申请状态": "PENDING",
        }
    )

    assert result.actor_id == "ou_user"
    assert result.actor_name == "Test User"
    assert result.modified_at == datetime.fromtimestamp(1788946000, tz=UTC)
    assert set(result.business_fields) == {"分配BD", "处理状态", "处理结果", "备注"}


def test_parse_feishu_sample_change_requires_modifier() -> None:
    with pytest.raises(TypeError, match="last modifier"):
        parse_feishu_sample_change({"最后修改时间": 1788946000000})


def test_business_field_filter_drops_system_and_unknown_fields() -> None:
    result = filter_feishu_business_fields(
        {
            "分配BD": "BD A",
            "备注": "Keep",
            "TK申请状态": "SHIPPED",
            "unexpected": "drop",
        }
    )

    assert result == {"分配BD": "BD A", "备注": "Keep"}
