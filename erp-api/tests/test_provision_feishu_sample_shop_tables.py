from scripts.provision_feishu_sample_shop_tables import (
    _created_table_id,
    _field_body,
    _table_body,
)


def test_create_table_id_accepts_current_and_legacy_response_shapes() -> None:
    assert _created_table_id({"table_id": "tbl-current"}) == "tbl-current"
    assert _created_table_id({"table": {"table_id": "tbl-legacy"}}) == "tbl-legacy"


def test_create_table_body_includes_source_primary_field() -> None:
    source_fields = [
        {"field_name": "Shop Name", "type": 1, "is_primary": True},
        {"field_name": "首次发现时间", "type": 5, "is_primary": False},
    ]

    assert _table_body("跨境3样品申请", source_fields) == {
        "table": {
            "name": "跨境3样品申请",
            "default_view_name": "最新申请",
            "fields": [{"field_name": "Shop Name", "type": 1}],
        }
    }


def test_clone_select_field_strips_source_option_ids() -> None:
    field = {
        "field_name": "TK申请状态",
        "type": 3,
        "property": {
            "options": [
                {"id": "source-option", "name": "PENDING", "color": 2},
            ]
        },
    }

    assert _field_body(field) == {
        "field_name": "TK申请状态",
        "type": 3,
        "property": {"options": [{"name": "PENDING", "color": 2}]},
    }


def test_clone_date_field_keeps_only_supported_properties() -> None:
    field = {
        "field_name": "首次发现时间",
        "type": 5,
        "property": {
            "date_formatter": "yyyy/MM/dd HH:mm",
            "auto_fill": False,
            "unsupported": "value",
        },
    }

    assert _field_body(field) == {
        "field_name": "首次发现时间",
        "type": 5,
        "property": {
            "date_formatter": "yyyy/MM/dd HH:mm",
            "auto_fill": False,
        },
    }
