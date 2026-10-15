"""Shop-scoped creator projection with per-shop metrics and stable identity."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from scripts.daily_valid_creator_core import (
    SHOP_LINES,
    SHOP_ORDER,
    SHOP_ZONE,
    account_key,
    amount,
    date_millis,
    date_value,
)

SHOP_MATCH_LABELS = {"本土店": "本土2店"}


def shop_record_key(fields: dict) -> tuple[str, str]:
    account = account_key(fields.get("账号名称"))
    label = str(fields.get("匹配店铺") or "").strip()
    shop = "本土店" if label in {"本土店", "本土2店"} else label
    if not account:
        raise ValueError("Creator row has an invalid account key")
    if shop and shop not in SHOP_LINES:
        raise ValueError("Creator row must contain exactly one verified shop")
    return account, shop


def desired_shop_rows(base, high, low, windows, sample_window) -> dict:
    if any(set(value) != set(SHOP_ORDER) for value in (high, low, windows)):
        raise ValueError("Complete five-shop source data is required")
    activity = defaultdict(lambda: {"gmv": Decimal("0.00"), "video": 0,
                                    "live": 0, "latest": date.min})
    for shop in SHOP_ORDER:
        creator_end = windows[shop]["creators"][1]
        for row in high[shop]["creators"]:
            source_key = (account_key(row.get("username")), shop)
            gmv = amount(row.get("affiliateGmvMinor")) / 100
            if source_key in base and gmv > 0:
                value = activity[source_key]
                value["gmv"] += gmv
                value["latest"] = max(value["latest"], creator_end)
        for resource, rows, count, identity, timestamp in (
            ("videos", low[shop]["videos"], "video", "creatorUsername", "videoPostTime"),
            ("liveAccounts", high[shop]["liveAccounts"], "live", "username", "startTime"),
        ):
            start, end = windows[shop][resource]
            for row in rows:
                fields = row.get("fields") or {} if resource == "liveAccounts" else row
                username = fields.get(identity)
                if resource == "videos":
                    username = username or fields.get("creatorNickname")
                source_key = (account_key(username), shop)
                day = date_value(fields.get(timestamp), SHOP_ZONE)
                if source_key in base and day is not None and start <= day <= end:
                    value = activity[source_key]
                    value[count] += 1
                    value["latest"] = max(value["latest"], day)
    for key, source in base.items():
        approved = source["sample_day"]
        if key not in activity and approved and sample_window[0] <= approved <= sample_window[1]:
            activity[key]  # A declared cooperation shop is evidence, not a GMV guess.
    desired = {}
    for key, value in activity.items():
        source = base[key]
        approved = source["sample_day"]
        has_sample = bool(approved and sample_window[0] <= approved <= sample_window[1])
        reasons = [label for present, label in (
            (value["gmv"] > 0, "有业绩"), (value["video"] > 0, "有视频产出"),
            (value["live"] > 0, "有直播产出"), (has_sample, "有寄样"),
        ) if present]
        fields = {
            "账号名称": source["account"], "BD负责人": source["bd"],
            "匹配店铺": SHOP_MATCH_LABELS.get(key[1], key[1]),
            "最近有效日期": date_millis(max(value["latest"], approved if has_sample else date.min)),
            "同意样品日期": date_millis(approved) if approved else None,
            "业绩": float(value["gmv"].quantize(Decimal("0.01"))),
            "视频数": value["video"], "直播数": value["live"],
            "保留原因": "；".join(reasons),
            "数据质量备注": (f"多个BD负责人，已按最新同意样品日期选取：{source['bd']}"
                           if source["conflict"] else ""),
        }
        if shop_record_key(fields) != key:
            raise ValueError("Projected shop identity mismatch")
        desired[key] = fields
    if not desired:
        raise ValueError("No valid creator/shop rows")
    return desired
