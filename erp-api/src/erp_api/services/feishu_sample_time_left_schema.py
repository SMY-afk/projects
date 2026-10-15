from __future__ import annotations

SAMPLE_TIME_LEFT_FIELD_NAME = "样品申请剩余时间"
SAMPLE_TIME_LEFT_FIELD_TYPE = 1
SAMPLE_TIME_LEFT_UI_TYPE = "Text"


async def ensure_sample_time_left_field(client, *, apply: bool) -> str:
    fields = await client.list_field_metadata()
    existing = fields.get(SAMPLE_TIME_LEFT_FIELD_NAME)
    if existing is not None:
        if existing.field_type != SAMPLE_TIME_LEFT_FIELD_TYPE:
            raise ValueError("Feishu sample time-left field must remain text.")
        return "exists"
    if not apply:
        return "would_create"
    created = await client.create_field_definition(
        field_name=SAMPLE_TIME_LEFT_FIELD_NAME,
        field_type=SAMPLE_TIME_LEFT_FIELD_TYPE,
        ui_type=SAMPLE_TIME_LEFT_UI_TYPE,
        field_property={},
    )
    if created.field_type != SAMPLE_TIME_LEFT_FIELD_TYPE:
        raise RuntimeError("Feishu sample time-left field creation is invalid.")
    return "created"
