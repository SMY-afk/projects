"""Reconcile one owned record per order, retaining resolved history and user fields."""
from decimal import Decimal, InvalidOperation

from erp_api.services.logistics_feishu_fields import (
    KEY_FIELD,
    OWNED_FIELDS,
    RESOLVED,
    STATE_FIELD,
)


def plain(value):
    if value is None or value == []:
        return ""
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return "".join(item.get("text", "") for item in value)
    return value


def same_value(name, left, right):
    left, right = plain(left), plain(right)
    if name in {"创建至发货（小时）", "发货至真实发货（小时）", "真实多久送达（天）"} and left != "" and right != "":
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:
            return False
    return left == right


def index_records(records, tenant):
    owned = {}
    for record in records:
        key = plain(record.fields.get(KEY_FIELD))
        if not key:
            continue
        if not isinstance(key, str) or not key.startswith(str(tenant) + ":"):
            raise ValueError("Feishu table contains a key outside the configured tenant")
        if key in owned:
            raise ValueError("Feishu contains duplicate ERP order keys")
        owned[key] = record
    return owned


def build_plan(desired, records, tenant, now_text):
    owned = index_records(records, tenant)
    blank = [record for record in records if not any(plain(v) for v in record.fields.values())]
    creates, updates = [], []
    seen = set()
    for row in desired:
        key = row[KEY_FIELD]
        if key in seen:
            raise ValueError("The source contains duplicate ERP order keys")
        seen.add(key)
        prior = owned.get(key)
        if prior is None:
            if row[STATE_FIELD] == RESOLVED:
                raise ValueError("An untracked resolved order cannot be inserted")
            row = {**row, "首次接入飞书时间": now_text, "解除预警时间": ""}
            if blank:
                updates.append((blank.pop(0).record_id, row))
            else:
                creates.append(row)
            continue
        row = {**row, "首次接入飞书时间": plain(prior.fields.get("首次接入飞书时间")) or now_text,
               "解除预警时间": (plain(prior.fields.get("解除预警时间")) or now_text)
               if row[STATE_FIELD] == RESOLVED else ""}
        changed = any(not same_value(k, prior.fields.get(k), v)
                      for k, v in row.items() if k != "最近飞书同步时间")
        if changed:
            updates.append((prior.record_id, row))
    unverified = [key for key, record in owned.items()
                  if plain(record.fields.get(STATE_FIELD)) != RESOLVED and key not in seen]
    if unverified:
        raise ValueError("Active Feishu records are missing from the complete source snapshot")
    if any(set(row) - set(OWNED_FIELDS) for row in creates + [row for _, row in updates]):
        raise ValueError("The sync plan contains a field outside logistics ownership")
    return {"creates": creates, "updates": updates}
