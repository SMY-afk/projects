from types import SimpleNamespace

import pytest

from erp_api.services.feishu_sample_time_left_schema import (
    SAMPLE_TIME_LEFT_FIELD_NAME,
    ensure_sample_time_left_field,
)


class Client:
    def __init__(self, field=None):
        self.field = field
        self.created = []

    async def list_field_metadata(self):
        return {SAMPLE_TIME_LEFT_FIELD_NAME: self.field} if self.field else {}

    async def create_field_definition(self, **definition):
        self.created.append(definition)
        return SimpleNamespace(field_type=definition["field_type"])


@pytest.mark.asyncio
async def test_missing_time_left_field_is_created_as_text() -> None:
    client = Client()

    result = await ensure_sample_time_left_field(client, apply=True)

    assert result == "created"
    assert client.created == [
        {
            "field_name": SAMPLE_TIME_LEFT_FIELD_NAME,
            "field_type": 1,
            "ui_type": "Text",
            "field_property": {},
        }
    ]


@pytest.mark.asyncio
async def test_preview_does_not_create_missing_time_left_field() -> None:
    client = Client()

    assert await ensure_sample_time_left_field(client, apply=False) == "would_create"
    assert client.created == []


@pytest.mark.asyncio
async def test_existing_time_left_field_must_remain_text() -> None:
    client = Client(SimpleNamespace(field_type=2))

    with pytest.raises(ValueError, match="must remain text"):
        await ensure_sample_time_left_field(client, apply=False)
