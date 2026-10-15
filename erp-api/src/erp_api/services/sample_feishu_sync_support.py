from __future__ import annotations

from decimal import Decimal, InvalidOperation

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_record_index import SYNC_KEY_FIELD

_RECENT_SYNC_FIELD = "最近同步时间"


def index_records(
    records,
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    existing: dict[str, str] = {}
    remote_fields: dict[str, dict[str, object]] = {}
    for record in records:
        fields = record.snapshot.fields
        sync_key = fields.get(SYNC_KEY_FIELD)
        if sync_key in (None, ""):
            continue
        if not isinstance(sync_key, str) or not sync_key.strip():
            raise FeishuSampleError("Feishu sync key is invalid or duplicated.")
        sync_key = sync_key.strip()
        if sync_key in existing:
            raise FeishuSampleError("Feishu sync key is invalid or duplicated.")
        existing[sync_key] = record.record_id
        remote_fields[record.record_id] = fields
    return existing, remote_fields


def fields_match(expected: dict[str, object], actual: dict[str, object]) -> bool:
    return all(
        _field_values_match(value, actual.get(name))
        for name, value in expected.items()
        if name != _RECENT_SYNC_FIELD
    )


def _field_values_match(expected: object, actual: object) -> bool:
    if expected in (None, "") and actual in (None, ""):
        return True
    if (
        isinstance(expected, (int, float, Decimal))
        and not isinstance(expected, bool)
        and isinstance(actual, str)
    ):
        try:
            expected_number = Decimal(str(expected))
            actual_number = Decimal(actual.strip())
        except (InvalidOperation, ValueError):
            return False
        return (
            expected_number.is_finite()
            and actual_number.is_finite()
            and expected_number == actual_number
        )
    return expected == actual
