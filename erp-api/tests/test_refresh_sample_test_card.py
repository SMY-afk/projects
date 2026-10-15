from types import SimpleNamespace
from uuid import uuid4

from scripts.refresh_sample_test_card import _table_id


def test_table_id_uses_shop_mapping_first() -> None:
    shop_id = uuid4()
    settings = SimpleNamespace(
        feishu_sample_shop_table_ids={shop_id: "shop-table"},
        feishu_sample_table_id="default-table",
    )

    assert _table_id(settings, shop_id) == "shop-table"


def test_table_id_falls_back_to_default_table() -> None:
    settings = SimpleNamespace(
        feishu_sample_shop_table_ids={},
        feishu_sample_table_id="default-table",
    )

    assert _table_id(settings, uuid4()) == "default-table"
