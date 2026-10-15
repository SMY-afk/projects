from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SampleMetricFieldSpec:
    field_name: str
    ui_type: str
    field_property: dict[str, object]
    field_type: int = 2


@dataclass(frozen=True)
class SampleMetricSchemaResult:
    created_fields: tuple[str, ...]
    updated_fields: tuple[str, ...]


SAMPLE_METRIC_FIELD_SPECS = (
    SampleMetricFieldSpec(
        "30日GMV",
        "Currency",
        {"formatter": "0.00", "currency_code": "USD"},
    ),
    SampleMetricFieldSpec("30日内容数", "Number", {"formatter": "0"}),
    SampleMetricFieldSpec("平均视频播放量", "Number", {"formatter": "0"}),
    SampleMetricFieldSpec("样品履约率", "Number", {"formatter": "0.00%"}),
    SampleMetricFieldSpec("30日销量", "Number", {"formatter": "0"}),
    SampleMetricFieldSpec("样品评分", "Number", {"formatter": "0"}),
)


async def configure_sample_metric_fields(client) -> SampleMetricSchemaResult:
    existing = await client.list_field_metadata()
    created: list[str] = []
    updated: list[str] = []
    for spec in SAMPLE_METRIC_FIELD_SPECS:
        definition = {
            "field_name": spec.field_name,
            "field_type": spec.field_type,
            "ui_type": spec.ui_type,
            "field_property": spec.field_property,
        }
        field = existing.get(spec.field_name)
        if field is None:
            await client.create_field_definition(**definition)
            created.append(spec.field_name)
            continue
        if field.field_type != spec.field_type:
            raise ValueError(
                f"Feishu metric field must remain numeric: {spec.field_name}."
            )
        await client.update_field_definition(field.field_id, **definition)
        updated.append(spec.field_name)
    return SampleMetricSchemaResult(tuple(created), tuple(updated))
