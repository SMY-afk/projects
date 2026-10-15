"""Field-only correction; never assume newly created records exist in old backups."""
RECOVERY_FIELDS = frozenset({"匹配店铺", "数据质量备注", "最新更新时间"})


def expected_recovery_fields(record_id, before, original, corrected_ids):
    if record_id not in corrected_ids:
        return before
    return {**before, **{name: original[record_id].get(name) for name in RECOVERY_FIELDS}}
