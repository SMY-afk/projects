from __future__ import annotations


def _metric(
    field: str,
    label: str,
    definition: str,
    value_type: str,
    unit: str,
    window_scope: str = "query_window",
) -> dict[str, object]:
    item: dict[str, object] = {
        "field": field,
        "label": label,
        "definition": definition,
        "valueType": value_type,
        "unit": unit,
        "windowScope": window_scope,
        "nullDisplay": "—",
    }
    if value_type == "money_minor":
        item["currencySource"] = "query.currency"
        item["displayUnit"] = "major_currency_unit"
    if value_type == "decimal_ratio":
        item["displayUnit"] = "percent"
    return item


CREATOR_DISPLAY_METRICS = (
    _metric(
        "username",
        "达人",
        "达人用户名；属于身份展示字段，不参与窗口聚合。",
        "string",
        "none",
        "identity",
    ),
    _metric(
        "affiliateGmvMinor",
        "联盟 GMV",
        "所选窗口内该达人产生的联盟成交总额。",
        "money_minor",
        "minor_currency_unit",
    ),
    _metric(
        "affiliateVideoGmvMinor",
        "视频 GMV",
        "所选窗口内该达人带货视频产生的联盟成交总额。",
        "money_minor",
        "minor_currency_unit",
    ),
    _metric(
        "affiliateLiveGmvMinor",
        "直播 GMV",
        "所选窗口内该达人直播产生的联盟成交总额。",
        "money_minor",
        "minor_currency_unit",
    ),
    _metric(
        "estimatedCommissionMinor",
        "预计佣金",
        "所选窗口内按平台当前归因状态估算的联盟佣金。",
        "money_minor",
        "minor_currency_unit",
    ),
    _metric(
        "affiliateOrderCount",
        "订单量",
        "所选窗口内归因给该达人的联盟订单数量。",
        "integer",
        "orders",
    ),
    _metric(
        "itemsSold",
        "成交件数",
        "所选窗口内归因给该达人的成交商品件数。",
        "integer",
        "items",
    ),
    _metric(
        "productImpressions",
        "商品曝光",
        "所选窗口内联盟商品获得的曝光次数。",
        "integer",
        "impressions",
    ),
    _metric(
        "clickThroughRate",
        "点击率",
        "平台导出的点击率；存储为 0 到 1 的十进制比率，页面按百分比显示。",
        "decimal_ratio",
        "ratio",
    ),
    _metric(
        "affiliateVideoCount",
        "带货视频数",
        "所选窗口内计入联盟表现的带货视频数量。",
        "integer",
        "videos",
    ),
    _metric(
        "affiliateLiveCount",
        "直播数",
        "所选窗口内计入联盟表现的直播场次数量。",
        "integer",
        "live_sessions",
    ),
    _metric(
        "affiliateFollowerCount",
        "粉丝数",
        "报表生成时观察到的达人粉丝数，不是窗口内累计值。",
        "integer",
        "followers",
        "observation_at_report_generation",
    ),
)


def affiliate_center_display_contract() -> dict[str, dict[str, object]]:
    return {
        "creators": {
            "status": "active",
            "rowGrain": "one_creator_per_report_revision",
            "currencySource": "query.currency",
            "windowSemantics": "inclusive_shop_local_dates",
            "metrics": [dict(item) for item in CREATOR_DISPLAY_METRICS],
            "defaultSort": [
                {"field": "affiliateGmvMinor", "direction": "desc"},
                {"field": "username", "direction": "asc"},
            ],
            "sorting": {
                "scope": "selected_complete_revision",
                "execution": "server_side",
                "nulls": "last",
                "tieBreaker": "username_asc",
            },
        },
        "videos": {
            "status": "awaiting_verified_payload",
            "rowGrain": "one_video_per_report_revision",
            "currencySource": "query.currency",
            "windowSemantics": "inclusive_shop_local_dates",
            "metrics": [],
            "defaultSort": [],
            "activationRule": (
                "真实页面响应完成字段、单位和排序验证后才能启用生产指标。"
            ),
        },
    }
