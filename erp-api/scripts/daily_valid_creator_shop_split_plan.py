"""Plan a bounded, no-delete migration of exactly 71 legacy double-shop rows."""

import hashlib
import json
from copy import deepcopy

from scripts.daily_valid_creator_shop_rows import shop_record_key
from scripts.daily_valid_creator_sync import equal_field

METRIC_FIELDS = ("业绩", "视频数", "直播数", "最近有效日期", "保留原因")


def split_plan(current: list[dict], desired: dict, expected_count: int = 71) -> dict:
    singles = set()
    legacy = []
    ids = set()
    for row in current:
        if not row.get("record_id") or row["record_id"] in ids:
            raise ValueError("Target IDs are missing or duplicated")
        ids.add(row["record_id"])
        fields = row["fields"]
        label = str(fields.get("匹配店铺") or "").strip()
        if "；" not in label:
            key = shop_record_key(fields)
            if key in singles and key[1]:
                raise ValueError("Target already has duplicate shop identities")
            singles.add(key)
            continue
        labels = label.split("；")
        keys = [shop_record_key({**fields, "匹配店铺": shop}) for shop in labels]
        if len(keys) != 2 or len(set(keys)) != 2:
            raise ValueError("Legacy match is not exactly two shops")
        legacy.append((row, labels, keys))
    if len(legacy) != expected_count:
        raise ValueError("Legacy double-shop count differs from approved scope")
    updates, creates, projected = [], [], deepcopy(current)
    expected_keys = set(singles)
    for row, labels, keys in legacy:
        fields = row["fields"]
        replacements = []
        for label, key in zip(labels, keys, strict=True):
            if key in expected_keys:
                raise ValueError("Split would duplicate an existing shop identity")
            expected_keys.add(key)
            evidence = desired.get(key)
            if evidence is None or shop_record_key(evidence) != key:
                raise ValueError("A matched shop has no complete current source projection")
            replacement = {**fields, "匹配店铺": label}
            replacement.update({name: evidence.get(name) for name in METRIC_FIELDS})
            replacements.append(replacement)
        change = {name: value for name, value in replacements[0].items()
                  if not equal_field(name, fields.get(name), value)}
        updates.append((row["record_id"], change))
        creates.append(replacements[1])
        next(item for item in projected if item["record_id"] == row["record_id"])["fields"] = replacements[0]
        projected.append({"record_id": "planned:" + row["record_id"], "fields": replacements[1]})
    operations = {"update": sorted(updates), "create": creates, "delete": []}
    digest = hashlib.sha256(json.dumps(
        operations, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return {"operations": operations, "hash": digest, "projected": projected,
            "updated": len(updates), "created": len(creates),
            "final_count": len(projected)}


def verify_split(baseline, after, plan, today_millis):
    if len(after) != plan["final_count"]:
        raise RuntimeError("Split readback count mismatch")
    by_id = {row["record_id"]: row for row in after}
    by_key = {shop_record_key(row["fields"]): row for row in after}
    scoped = [row for row in after if shop_record_key(row["fields"])[1]]
    if len(by_id) != len(after) or len({shop_record_key(row["fields"]) for row in scoped}) != len(scoped):
        raise RuntimeError("Split readback identities are duplicated")
    modified = {record_id for record_id, _ in plan["operations"]["update"]}
    for original in baseline:
        actual = by_id.get(original["record_id"])
        if actual is None:
            raise RuntimeError("Split lost an original record ID")
        if original["record_id"] not in modified and actual["fields"] != original["fields"]:
            raise RuntimeError("Split changed an unrelated record")
    for projected in plan["projected"]:
        actual = by_key[shop_record_key(projected["fields"])]
        for name, value in projected["fields"].items():
            if name != "最新更新时间" and not equal_field(name, actual["fields"].get(name), value):
                raise RuntimeError("Split per-shop field mismatch")
        if ((projected["record_id"] in modified or projected["record_id"].startswith("planned:"))
                and actual["fields"].get("最新更新时间") != today_millis):
            raise RuntimeError("Split changed-row timestamp mismatch")
