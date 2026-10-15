"""Repair audited legacy multi-shop rows without deleting history."""
import hashlib
import json
from copy import deepcopy

from scripts.daily_valid_creator_accounts import COOPERATION_SHOPS
from scripts.daily_valid_creator_core import BUSINESS_FIELDS, account_key
from scripts.daily_valid_creator_shop_rows import shop_record_key
from scripts.daily_valid_creator_sync import equal_field


def migration_preview(desired, current, ordinary_preview):
    projected = deepcopy(current)
    legacy = [row for row in projected if "；" in str(row["fields"].get("匹配店铺") or "")]
    if len(legacy) != 71:
        raise ValueError("Legacy double-shop count differs from approved scope")
    present = {shop_record_key(row["fields"]) for row in projected if row not in legacy}
    update, create, splits, unverified = {}, {}, 0, 0
    confirmed = []
    for row in legacy:
        fields = row["fields"]
        account = account_key(fields.get("账号名称"))
        old_shops = [COOPERATION_SHOPS.get(label) for label in str(fields["匹配店铺"]).split("；")]
        candidates = sorted((key for key in desired if key[0] == account and key[1]),
                            key=lambda key: (key[1] not in old_shops, key))
        candidates = [key for key in candidates if key not in present]
        if candidates:
            if len(candidates) > 1:
                confirmed.append({"account": str(fields["账号名称"]).strip(),
                    "record_id": row["record_id"], "shops": sorted(key[1] for key in candidates)})
            fields.update(desired[candidates[0]])
            present.add(candidates[0])
            for ordinal, key in enumerate(candidates[1:], 1):
                record_id = f"planned:{row['record_id']}:{ordinal}"
                replacement = deepcopy(desired[key])
                projected.append({"record_id": record_id, "fields": replacement})
                create[record_id] = replacement
                present.add(key)
            splits += len(candidates) > 1
        else:
            old = str(fields["匹配店铺"])
            fields["匹配店铺"] = ""
            fields["数据质量备注"] = str(fields.get("数据质量备注") or "") + (
                f"；历史匹配店铺待核验，未推断合作店铺；旧值：{old}")
            unverified += 1
        original = next(item["fields"] for item in current if item["record_id"] == row["record_id"])
        update[row["record_id"]] = {name: fields.get(name) for name in BUSINESS_FIELDS
                                    if not equal_field(name, original.get(name), fields.get(name))}
    ordinary = ordinary_preview(desired, projected)
    for record_id, changes in ordinary["operations"]["update"]:
        if record_id in create:
            create[record_id] = {**create[record_id], **changes}
        else:
            update[record_id] = {**update.get(record_id, {}), **changes}
    if ordinary["operations"]["delete"]:
        raise ValueError("Schema correction cannot delete records")
    operations = {"update": sorted(update.items()),
                  "create": [*create.values(), *ordinary["operations"]["create"]],
                  "delete": []}
    digest = hashlib.sha256(json.dumps(operations, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**ordinary, "operations": operations, "hash": digest,
            "updates": len(update), "creates": len(operations["create"]),
            "legacy_shop_splits": splits, "legacy_corrected_rows": len(legacy),
            "confirmed_multi_shop_rows": sorted(confirmed, key=lambda row: row["account"].casefold()),
            "legacy_unverified_rows": unverified, "target_count": len(current)}
