"""Reuse a proven existing blank-shop row without deleting historical rows."""
from copy import deepcopy

from scripts.daily_valid_creator_core import date_value
from scripts.daily_valid_creator_shop_rows import shop_record_key


def adoption_preview(desired, current, ordinary_preview):
    projected = deepcopy(current)
    present = {shop_record_key(row["fields"]) for row in current}
    adopted = {}
    for key, fields in sorted(desired.items()):
        if not key[1] or key in present:
            continue
        candidates = [row for row in projected
            if shop_record_key(row["fields"]) == (key[0], "")
            and str(row["fields"].get("BD负责人") or "").strip() == str(fields.get("BD负责人") or "").strip()
            and date_value(fields.get("同意样品日期")) is not None
            and date_value(row["fields"].get("同意样品日期")) == date_value(fields.get("同意样品日期"))]
        if not candidates:
            continue
        candidate = max(candidates, key=lambda row: row["record_id"])
        adopted[candidate["record_id"]] = {"匹配店铺": fields["匹配店铺"]}
        candidate["fields"].update(adopted[candidate["record_id"]])
        present.add(key)
    if not adopted:
        return None
    plan = ordinary_preview(desired, projected)
    updates = dict(plan["operations"]["update"])
    for record_id, fields in adopted.items():
        updates[record_id] = {**fields, **updates.get(record_id, {})}
    import hashlib
    import json

    operations = {**plan["operations"], "update": sorted(updates.items())}
    digest = hashlib.sha256(json.dumps(operations, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**plan, "operations": operations, "hash": digest, "updates": len(updates),
            "adopted_blank_shop_rows": len(adopted)}
