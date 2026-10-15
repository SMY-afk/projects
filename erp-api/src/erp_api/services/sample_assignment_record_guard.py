from __future__ import annotations

from erp_api.services.sample_assignment_record_fields import creator_record_key

SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000


def validate_assignment_record_update(
    current: dict[str, object], desired: dict[str, object]
) -> None:
    current_key = creator_record_key(current)
    desired_key = creator_record_key(desired)
    if not all(current_key) or current_key != desired_key:
        raise RuntimeError("Feishu assignment record identity changed; manual review is required.")
    current_number = current.get("分配编号")
    desired_number = desired.get("分配编号")
    current_bd = current.get("分配BD")
    desired_bd = desired.get("分配BD")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (current_number, desired_number, current_bd, desired_bd)
    ):
        raise RuntimeError("Feishu assignment record identity is incomplete.")
    if current_bd == desired_bd:
        return
    if current_number == desired_number:
        raise RuntimeError("Feishu assignment record BD changed; manual review is required.")
    current_time = current.get("分配时间")
    desired_time = desired.get("分配时间")
    if (
        isinstance(current_time, bool)
        or isinstance(desired_time, bool)
        or not isinstance(current_time, int)
        or not isinstance(desired_time, int)
    ):
        raise TypeError("Feishu assignment record time is incomplete.")
    elapsed = desired_time - current_time
    if elapsed < SEVEN_DAYS_MS:
        raise RuntimeError(
            "Feishu assignment record seven-day owner conflict; manual review is required."
        )
