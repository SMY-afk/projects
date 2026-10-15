from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from erp_api.services.sample_notification_card_components import (
    collapsible_panel,
    escape_text,
    markdown,
    metric_grid,
)
from erp_api.services.sample_notification_profile_values import (
    date_text as _date_text,
)
from erp_api.services.sample_notification_profile_values import (
    distribution_summary as _distribution_summary,
)
from erp_api.services.sample_notification_profile_values import (
    integer_text as _integer_text,
)
from erp_api.services.sample_notification_profile_values import (
    label_summary as _label_summary,
)
from erp_api.services.sample_notification_profile_values import (
    mapping as _mapping,
)
from erp_api.services.sample_notification_profile_values import (
    money as _money,
)
from erp_api.services.sample_notification_profile_values import (
    out_of_five as _out_of_five,
)
from erp_api.services.sample_notification_profile_values import (
    percentage_bps as _percentage_bps,
)
from erp_api.services.sample_notification_profile_values import (
    score as _score,
)
from erp_api.services.sample_notification_profile_values import (
    text as _text,
)


def build_profile_sections(
    snapshot: object,
    *,
    currency: str | None,
    pps: Decimal | None = None,
    rating: Decimal | None = None,
) -> list[dict[str, object]]:
    profile = _mapping(snapshot)
    candidates = (
        (
            _profile_and_score_panel(profile, pps=pps, rating=rating),
            _sales_panel(profile, currency),
            _media_panel(profile, currency),
            _audience_panel(profile),
        )
        if profile.get("schema_version") == 2
        else (None, None, None, None)
    )
    panel_specs = (
        ("达人资料与样品表现", "creator-profile-and-score"),
        ("销量与合作", "creator-sales-and-cooperation"),
        ("视频、直播与趋势", "creator-media-and-trends"),
        ("粉丝画像", "creator-audience"),
    )
    return [
        panel
        or collapsible_panel(
            title,
            [markdown("暂无数据")],
            element_id=element_id,
        )
        for panel, (title, element_id) in zip(candidates, panel_specs, strict=True)
    ]


def sample_score_summary(snapshot: object) -> str:
    score = _mapping(_mapping(snapshot).get("sample_score"))
    overall = _score(score.get("overall"))
    grade = _text(score.get("grade_label"))
    if overall == "—":
        return "—"
    return f"{overall}/100" + (f" · {escape_text(grade)}" if grade else "")


def profile_brief(snapshot: object) -> str | None:
    profile = _mapping(snapshot)
    if profile.get("schema_version") != 2:
        return None
    values: list[str] = []
    if location := _text(profile.get("location")):
        values.append(f"📍 {escape_text(location, limit=60)}")
    if categories := _label_summary(profile.get("creator_categories"), limit=2):
        values.append(f"类目 {escape_text(categories, limit=120)}")
    return "　".join(values) or None


def profile_window_summary(snapshot: object) -> str | None:
    profile = _mapping(snapshot)
    windows = (
        _mapping(_mapping(profile.get(section)).get("window"))
        for section in ("sales", "sample_score", "video", "audience", "trends")
    )
    window = next((item for item in windows if item), {})
    start = _date_text(window.get("start_at"))
    end = _date_text(window.get("end_at"))
    timezone = _text(window.get("timezone"))
    if start and end:
        result = f"画像窗口 {start} 至 {end}"
    elif window.get("kind") == "last_30_days":
        result = "画像窗口：近 30 天"
    else:
        return None
    return result + (f"（{escape_text(timezone, limit=24)}）" if timezone else "")


def _profile_and_score_panel(
    profile: Mapping[str, object],
    *,
    pps: Decimal | None,
    rating: Decimal | None,
) -> dict[str, object] | None:
    elements: list[dict[str, object]] = []
    details = []
    if bio := _text(profile.get("bio")):
        details.append(f"**简介**　{escape_text(bio)}")
    if location := _text(profile.get("location")):
        details.append(f"**地区**　{escape_text(location)}")
    pps_data = _mapping(profile.get("pps"))
    if description := _text(pps_data.get("description")):
        details.append(f"**PPS 说明**　{escape_text(description)}")
    if details:
        elements.append(markdown("\n".join(details)))

    score = _mapping(profile.get("sample_score"))
    top_metrics = [
        ("PPS", _out_of_five(pps)),
        ("PPS 等级", _text(pps_data.get("band_label")) or "—"),
        ("达人评分", _out_of_five(rating)),
        ("评价数", _integer_text(profile.get("rating_count"))),
        ("样品分", sample_score_summary(profile)),
    ]
    if any(value != "—" for _, value in top_metrics):
        elements.extend(metric_grid(top_metrics))

    sub_scores = [
        (label, _sample_metric(score, key))
        for key, label in (
            ("content_effect", "样品内容效果"),
            ("posting_freshness", "发文新鲜度"),
            ("selling_power", "带货力"),
            ("posting_effect", "发文效果"),
        )
        if _sample_metric(score, key) != "—"
    ]
    if sub_scores:
        elements.extend(metric_grid(sub_scores))
    if not elements:
        return None
    return collapsible_panel(
        "达人资料与样品表现",
        elements,
        element_id="creator-profile-and-score",
    )


def _sales_panel(
    profile: Mapping[str, object], currency: str | None
) -> dict[str, object] | None:
    sales = _mapping(profile.get("sales"))
    cooperation = _mapping(profile.get("cooperation"))
    metrics = [
        ("成交件数", _integer_text(sales.get("order_count"))),
        ("千次曝光成交金额", _money(sales.get("gmv_per_mille_minor"), currency)),
        ("客单价", _money(sales.get("average_order_value_minor"), currency)),
        ("预计发布率", _percentage_bps(cooperation.get("estimated_post_rate_bps"))),
        ("平均佣金率", _percentage_bps(cooperation.get("average_commission_rate_bps"))),
        ("合作商品", _integer_text(cooperation.get("product_count"))),
        ("品牌合作", _integer_text(cooperation.get("brand_collaboration_count"))),
    ]
    elements = metric_grid([(label, value) for label, value in metrics if value != "—"])
    lines = []
    if channels := _distribution_summary(sales.get("channel_shares"), limit=5):
        lines.append(f"**成交渠道**　{escape_text(channels)}")
    if categories := _distribution_summary(sales.get("category_shares"), limit=5):
        lines.append(f"**类目收入**　{escape_text(categories)}")
    if lines:
        elements.append(markdown("\n".join(lines)))
    if not elements:
        return None
    return collapsible_panel(
        "销量与合作",
        elements,
        element_id="creator-sales-and-cooperation",
    )


def _media_panel(
    profile: Mapping[str, object], currency: str | None
) -> dict[str, object] | None:
    elements: list[dict[str, object]] = []
    sales = _mapping(profile.get("sales"))
    video = _mapping(profile.get("video"))
    live = _mapping(profile.get("live"))
    if "gmv_per_mille_minor" not in video and "video_gmv_per_mille_minor" in sales:
        video = {**video, "gmv_per_mille_minor": sales["video_gmv_per_mille_minor"]}
    _append_media_metrics(
        elements, "视频数据", video, currency, gpm_label="Video GPM"
    )
    _append_media_metrics(
        elements, "直播数据", live, currency, gpm_label="LIVE GPM"
    )
    trends = _mapping(profile.get("trends"))
    trend_metrics = [
        ("GMV", _money(trends.get("gmv_minor"), currency)),
        ("销量", _integer_text(trends.get("units_sold"))),
        ("粉丝", _integer_text(trends.get("followers"))),
        ("视频播放", _integer_text(trends.get("video_views"))),
        ("互动率", _percentage_bps(trends.get("engagement_rate_bps"))),
    ]
    present_trends = [(label, value) for label, value in trend_metrics if value != "—"]
    if present_trends:
        elements.append(markdown("**趋势摘要**"))
        elements.extend(metric_grid(present_trends))
    if not elements:
        return None
    return collapsible_panel(
        "视频、直播与趋势",
        elements,
        element_id="creator-media-and-trends",
    )


def _append_media_metrics(
    elements: list[dict[str, object]],
    title: str,
    metrics: Mapping[str, object],
    currency: str | None,
    *,
    gpm_label: str,
) -> None:
    values = [
        (gpm_label, _money(metrics.get("gmv_per_mille_minor"), currency)),
        ("内容数", _integer_text(metrics.get("count"))),
        ("平均播放", _integer_text(metrics.get("average_view_count"))),
        ("平均互动率", _percentage_bps(metrics.get("average_engagement_rate_bps"))),
    ]
    present = [(label, value) for label, value in values if value != "—"]
    if present:
        elements.append(markdown(f"**{title}**"))
        elements.extend(metric_grid(present))


def _audience_panel(profile: Mapping[str, object]) -> dict[str, object] | None:
    audience = _mapping(profile.get("audience"))
    lines = []
    for label, value, limit in (
        ("性别", audience.get("gender"), 5),
        ("年龄", audience.get("age"), 8),
        ("前 5 名地区", audience.get("top_regions"), 5),
    ):
        if summary := _distribution_summary(
            value, limit=limit, fixed_decimals=2
        ):
            lines.append(f"**{label}**　{escape_text(summary)}")
    if not lines:
        return None
    return collapsible_panel(
        "粉丝画像",
        [markdown("\n".join(lines))],
        element_id="creator-audience",
    )


def _sample_metric(score: Mapping[str, object], key: str) -> str:
    value = _score(score.get(key))
    if value == "—":
        return value
    percentile = _percentage_bps(score.get(f"{key}_percentile_bps"))
    return f"{value}/100" + (f" · 超过 {percentile}" if percentile != "—" else "")
