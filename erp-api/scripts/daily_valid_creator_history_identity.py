"""Resolve historical identities only from explicitly declared master shops."""

from scripts.daily_valid_creator_accounts import COOPERATION_SHOPS
from scripts.daily_valid_creator_core import account_key, date_millis, date_value
from scripts.daily_valid_creator_shop_rows import SHOP_MATCH_LABELS

HISTORY_REASON = "历史留存；本轮无有效依据"
DUPLICATE_REASON = "历史留存；同账号同店重复记录"
PENDING_REASON = "待核验；总表缺失或合作店铺对应不明确"
HISTORY_NOTE = "依据最新完整达人建联总表核对，历史行不属于本轮有效投影"
PENDING_NOTE = "未从其他店铺活动推断合作店铺或BD；历史信息保留待人工核验"


def historical_reason(value):
    return str(value or "").strip().startswith(("历史留存", "待核验"))


def canonical_shop(fields):
    raw = str(fields.get("匹配店铺") or "").strip()
    return COOPERATION_SHOPS.get(raw, None) if raw else ""


def historical_key(fields):
    raw = str(fields.get("匹配店铺") or "").strip()
    shop = canonical_shop(fields)
    return account_key(fields.get("账号名称")), shop if shop is not None else raw


def identity_fields(key, source):
    approved = source.get("sample_day")
    return {"账号名称": source["account"], "BD负责人": source["bd"],
            "匹配店铺": SHOP_MATCH_LABELS.get(key[1], key[1]),
            "同意样品日期": date_millis(approved) if approved else None}


def matching_master_key(fields, candidates):
    """Known exact shop wins; otherwise migration requires unique provenance."""
    account = account_key(fields.get("账号名称"))
    shop = canonical_shop(fields)
    if shop is not None and (account, shop) in candidates:
        return account, shop
    declared = {key: row for key, row in candidates.items() if key[1]}
    if len(declared) == 1:
        return next(iter(declared))
    owner = str(fields.get("BD负责人") or "").strip()
    approved = date_value(fields.get("同意样品日期"))
    matches = [key for key, row in declared.items() if owner
               and str(row.get("bd") or "").strip() == owner
               and row.get("sample_day") == approved]
    if len(matches) == 1:
        return matches[0]
    if not declared and (account, "") in candidates:
        return account, ""
    return None


def keeper_rank(row, key):
    fields = row["fields"]
    return (not historical_reason(fields.get("保留原因")),
            historical_key(fields) == key,
            date_value(fields.get("同意样品日期")) or date_value("0001-01-01"),
            row["record_id"])


def inactive_fields(fields, key, source, *, duplicate=False):
    result = identity_fields(key, source) if key is not None else {}
    if key is None and canonical_shop(fields) == "本土店":
        result["匹配店铺"] = "本土2店"
    result.update({"最近有效日期": None, "业绩": 0, "视频数": 0, "直播数": 0,
                   "保留原因": (DUPLICATE_REASON if duplicate else HISTORY_REASON)
                   if key is not None else PENDING_REASON,
                   "数据质量备注": HISTORY_NOTE if key is not None else PENDING_NOTE})
    return result
