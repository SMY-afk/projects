"""Pure source matching and Feishu field normalization for daily creator sync."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from scripts.daily_valid_creator_sample import sample_date

BUSINESS_FIELDS = (
    "账号名称",
    "BD负责人",
    "匹配店铺",
    "最近有效日期",
    "同意样品日期",
    "业绩",
    "视频数",
    "直播数",
    "保留原因",
    "数据质量备注",
)
SHOP_LINES = {
    "跨境3": "童车",
    "跨境7": "童车",
    "跨境4": "遥控车",
    "跨境12": "遥控车",
    "本土店": "遥控车",
}
SHOP_ORDER = tuple(SHOP_LINES)
SHOP_MATCH_LABELS = {"本土店": "本土2店"}
BEIJING = ZoneInfo("Asia/Shanghai")
SHOP_ZONE = ZoneInfo("America/Los_Angeles")
ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff]")


def account_key(value: object) -> str:
    return ZERO_WIDTH.sub("", str(value or "")).strip().lstrip("@").casefold()


def date_value(value: object, zone: ZoneInfo = BEIJING) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(zone).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) or str(value).strip().isdigit():
        number = float(value)
        if number > 100_000_000_000:
            number /= 1000
        if number > 1_000_000_000:
            return datetime.fromtimestamp(number, UTC).astimezone(zone).date()
    text = str(value).strip().replace("年", "-").replace("月", "-").replace("日", "")
    if "T" in text or ":" in text:
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.astimezone(zone).date() if parsed.tzinfo else parsed.date()
        except ValueError:
            return None
    if match := re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text):
        return date(*(int(part) for part in match.groups()))
    return None


def date_millis(day: date) -> int:
    return int(datetime.combine(day, time.min, BEIJING).timestamp() * 1000)


def amount(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Invalid affiliate amount") from exc


def validate_sources(
    feishu: dict,
    high: dict,
    low: dict,
    cutoffs: dict[str, dict[str, date]],
) -> dict:
    tables = feishu.get("tables")
    if feishu.get("source") != "feishu-bitable-readonly" or not isinstance(
        tables, list
    ):
        raise ValueError("Invalid Feishu source envelope")
    if len(tables) != 2 or {t.get("productLine") for t in tables} != {"童车", "遥控车"}:
        raise ValueError("Feishu prerequisite tables are missing or duplicated")
    for table in tables:
        rows = table.get("rows")
        if not isinstance(rows, list) or len(rows) != table.get("total"):
            raise ValueError("Incomplete Feishu prerequisite pagination")
        if any(
            set(row) != {"accountName", "bdOwner", "sampleApprovedDate"} for row in rows
        ):
            raise ValueError("Unexpected Feishu prerequisite fields")
    result = validate_erp_sources(high, low, cutoffs)
    return {"tables": tables, **result}


def validate_erp_sources(high, low, cutoffs):
    for label, payload in (("high", high), ("low", low)):
        if payload.get("source") != "local-erp-affiliate-center":
            raise ValueError(f"Invalid {label} ERP envelope")
        shops = payload.get("shops")
        if (
            not isinstance(shops, list)
            or len(shops) != len(SHOP_LINES)
            or {s.get("shopName") for s in shops} != set(SHOP_LINES)
        ):
            raise ValueError(f"Incomplete {label} ERP shop list")
        for shop in shops:
            if shop.get("productLine") != SHOP_LINES[shop["shopName"]]:
                raise ValueError("ERP product line mismatch")
            for section in ("creators", "videos", "liveAccounts"):
                items = shop.get(section)
                if not isinstance(items, list) or len(items) != shop.get(
                    "totals", {}
                ).get(section):
                    raise ValueError(f"Incomplete {shop['shopName']}.{section} total")
    high_by = {s["shopName"]: s for s in high["shops"]}
    low_by = {s["shopName"]: s for s in low["shops"]}
    if set(cutoffs) != set(SHOP_LINES):
        raise ValueError("Incomplete per-shop source cutoffs")
    windows = {}
    for name in SHOP_LINES:
        creator_end = cutoffs[name]["creators"]
        video_end = cutoffs[name]["videos"]
        live_end = cutoffs[name]["liveAccounts"]
        creator_start = creator_end - relativedelta(months=2)
        video_start = video_end - relativedelta(months=2)
        live_start = live_end - relativedelta(months=2)
        windows[name] = {
            "creators": (creator_start, creator_end),
            "videos": (video_start, video_end),
            "liveAccounts": (live_start, live_end),
        }
        for resource in ("creators", "liveAccounts"):
            start, end = windows[name][resource]
            if high_by[name]["sourceWindows"][resource] != {
                "from": start.isoformat(),
                "to": end.isoformat(),
            }:
                raise ValueError(f"{name}.{resource} source window mismatch")
        if low_by[name]["sourceWindows"]["videos"] != {
            "from": video_start.isoformat(),
            "to": video_end.isoformat(),
        }:
            raise ValueError(f"{name}.videos source window mismatch")
    return {
        "high": high_by,
        "low": low_by,
        "windows": windows,
    }


def select_base_accounts(
    tables: list[dict], sample_window: tuple[date, date]
) -> tuple[dict, int]:
    grouped = defaultdict(list)
    for table in tables:
        line = table["productLine"]
        for ordinal, row in enumerate(table["rows"]):
            key = account_key(row.get("accountName"))
            if key:
                grouped[(line, key)].append(
                    (sample_date(row.get("sampleApprovedDate"), sample_window), ordinal, row)
                )
    selected = {}
    conflicts = 0
    for key, candidates in grouped.items():
        ordered = sorted(candidates, key=lambda item: (item[0] or date.min, item[1]))
        latest_day, _, latest_row = ordered[-1]
        with_bd = [
            item for item in ordered if str(item[2].get("bdOwner") or "").strip()
        ]
        bd = str(with_bd[-1][2]["bdOwner"]).strip() if with_bd else ""
        owners = {str(item[2].get("bdOwner") or "").strip() for item in candidates}
        owners.discard("")
        conflicts += len(owners) > 1
        selected[key] = {
            "account": str(latest_row["accountName"]).strip(),
            "bd": bd,
            "sample_day": latest_day,
            "conflict": len(owners) > 1,
        }
    if not selected:
        raise ValueError("No usable Feishu creator accounts")
    return selected, conflicts


def desired_rows(
    base: dict,
    high: dict,
    low: dict,
    windows: dict[str, dict[str, tuple[date, date]]],
    sample_window: tuple[date, date],
) -> dict:
    activity = defaultdict(
        lambda: {
            "shops": set(),
            "gmv": Decimal("0.00"),
            "video": 0,
            "live": 0,
            "latest": date.min,
        }
    )
    for shop_name in SHOP_ORDER:
        line = SHOP_LINES[shop_name]
        _, creator_end = windows[shop_name]["creators"]
        video_start, video_end = windows[shop_name]["videos"]
        live_start, live_end = windows[shop_name]["liveAccounts"]
        for row in high[shop_name]["creators"]:
            key = (line, account_key(row.get("username")))
            gmv = amount(row.get("affiliateGmvMinor")) / 100
            if key not in base or gmv <= 0:
                continue
            item = activity[key]
            item["shops"].add(shop_name)
            item["gmv"] += gmv
            item["latest"] = max(item["latest"], creator_end)
        for row in low[shop_name]["videos"]:
            key = (
                line,
                account_key(row.get("creatorUsername") or row.get("creatorNickname")),
            )
            day = date_value(row.get("videoPostTime"), SHOP_ZONE)
            if key not in base or day is None or not video_start <= day <= video_end:
                continue
            item = activity[key]
            item["shops"].add(shop_name)
            item["video"] += 1
            item["latest"] = max(item["latest"], day)
        for row in high[shop_name]["liveAccounts"]:
            fields = row.get("fields") or {}
            key = (line, account_key(fields.get("username")))
            day = date_value(fields.get("startTime"), SHOP_ZONE)
            if key not in base or day is None or not live_start <= day <= live_end:
                continue
            item = activity[key]
            item["shops"].add(shop_name)
            item["live"] += 1
            item["latest"] = max(item["latest"], day)
    desired = {}
    eligible = set(activity) | {
        key
        for key, source in base.items()
        if source["sample_day"] and sample_window[0] <= source["sample_day"] <= sample_window[1]
    }
    for key in eligible:
        value = activity[key]
        source = base[key]
        has_sample = bool(
            source["sample_day"]
            and sample_window[0] <= source["sample_day"] <= sample_window[1]
        )
        reasons = [
            label
            for present, label in (
                (value["gmv"] > 0, "有业绩"),
                (value["video"] > 0, "有视频产出"),
                (value["live"] > 0, "有直播产出"),
            )
            if present
        ]
        if has_sample:
            reasons.append("有寄样")
        desired[key] = {
            "产品线": key[0],
            "账号名称": source["account"],
            "BD负责人": source["bd"],
            "匹配店铺": "；".join(
                SHOP_MATCH_LABELS.get(name, name)
                for name in SHOP_ORDER
                if name in value["shops"]
            ),
            "最近有效日期": date_millis(
                max(value["latest"], source["sample_day"] if has_sample else date.min)
            ),
            "同意样品日期": date_millis(source["sample_day"])
            if source["sample_day"]
            else None,
            "业绩": float(value["gmv"].quantize(Decimal("0.01"))),
            "视频数": value["video"],
            "直播数": value["live"],
            "保留原因": "；".join(reasons),
            "数据质量备注": (
                f"多个BD负责人，已按最新同意样品日期选取：{source['bd']}"
                if source["conflict"]
                else ""
            ),
        }
    if not desired or len(desired) != len(set(desired)):
        raise ValueError("Empty or duplicate desired creator result")
    return desired
