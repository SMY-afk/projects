import pytest

from erp_api.services.feishu_sample_fields import FeishuFieldMetadata
from erp_api.services.feishu_sample_metric_schema import (
    SAMPLE_METRIC_FIELD_SPECS,
    configure_sample_metric_fields,
)


class FakeClient:
    def __init__(self) -> None:
        self.updated = []
        self.created = []

    async def list_field_metadata(self):
        return {
            "30日GMV": FeishuFieldMetadata("fld-gmv", "30日GMV", 2, False),
            "样品履约率": FeishuFieldMetadata(
                "fld-fulfillment", "样品履约率", 2, False
            ),
        }

    async def update_field_definition(self, field_id, **definition):
        self.updated.append((field_id, definition))
        return FeishuFieldMetadata(field_id, definition["field_name"], 2, False)

    async def create_field_definition(self, **definition):
        self.created.append(definition)
        return FeishuFieldMetadata(
            f"fld-created-{len(self.created)}",
            definition["field_name"],
            2,
            False,
        )


@pytest.mark.asyncio
async def test_metric_schema_matches_tiktok_display_and_adds_sample_score() -> None:
    specs = {spec.field_name: spec for spec in SAMPLE_METRIC_FIELD_SPECS}

    assert specs["30日GMV"].ui_type == "Currency"
    assert specs["30日GMV"].field_property == {
        "formatter": "0.00",
        "currency_code": "USD",
    }
    assert specs["30日内容数"].field_property == {"formatter": "0"}
    assert specs["平均视频播放量"].field_property == {"formatter": "0"}
    assert specs["样品履约率"].field_property == {"formatter": "0.00%"}
    assert specs["30日销量"].field_property == {"formatter": "0"}
    assert specs["样品评分"].field_property == {"formatter": "0"}

    client = FakeClient()
    result = await configure_sample_metric_fields(client)

    assert set(result.updated_fields) == {"30日GMV", "样品履约率"}
    assert set(result.created_fields) == {
        "30日内容数",
        "平均视频播放量",
        "30日销量",
        "样品评分",
    }
    updated = {definition["field_name"]: definition for _, definition in client.updated}
    assert updated["样品履约率"]["field_property"] == {"formatter": "0.00%"}


@pytest.mark.asyncio
async def test_metric_schema_rejects_existing_non_number_field() -> None:
    client = FakeClient()

    async def wrong_fields():
        return {"30日GMV": FeishuFieldMetadata("fld-gmv", "30日GMV", 1, False)}

    client.list_field_metadata = wrong_fields

    try:
        await configure_sample_metric_fields(client)
    except ValueError as error:
        assert "30日GMV" in str(error)
    else:
        raise AssertionError("Expected a non-number field to be rejected.")
