from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from erp_api.services.sample_application_mapper import STATUS_LABELS
from erp_api.services.sample_notification_application_card import (
    build_application_elements,
)
from erp_api.services.sample_notification_card_components import (
    button_row,
    escape_text,
    markdown,
    metric_grid,
    open_url_button,
)
from erp_api.services.sample_notification_profile_sections import (
    build_profile_sections,
    profile_brief,
    profile_window_summary,
    sample_score_summary,
)


def build_sample_notification_card(
    task,
    record_url_template: str,
    *,
    is_test: bool,
    avatar_img_key: str | None = None,
    product_img_keys: tuple[str, ...] = (),
) -> dict[str, object]:
    bd_name = task.payload.get("assigned_bd_name")
    if not isinstance(bd_name, str) or not bd_name.strip():
        raise ValueError("Sample notification BD name is invalid.")
    record_url = record_url_template.replace(
        "{record_id}", quote(task.feishu_record_id, safe="")
    )
    if not _safe_https_url(record_url):
        raise ValueError("Sample notification record URL is invalid.")
    if any(
        image_key is not None and not _valid_img_key(image_key)
        for image_key in (avatar_img_key, *product_img_keys)
    ):
        raise ValueError("Sample notification image key is invalid.")

    username = _optional_text(task.creator_username)
    elements: list[dict[str, object]] = []
    if is_test:
        elements.append(_test_banner())
    elements.extend(
        (
            _identity(task, username, avatar_img_key),
            *metric_grid(_decision_metrics(task)),
        )
    )
    elements.extend(
        build_profile_sections(
            task.creator_profile_snapshot,
            currency=task.creator_gmv_currency,
            pps=task.creator_pps,
            rating=task.creator_rating,
        )
    )
    elements.extend(
        (
            *build_application_elements(
                task,
                bd_name.strip(),
                product_img_keys,
                formatted_deadline=_format_time(task.approve_expiration_at),
            ),
            button_row(_actions(record_url, username)),
            _data_note(task),
        )
    )
    status = STATUS_LABELS.get(task.platform_status, task.platform_status)
    title = "买返样品申请" if getattr(task, "sample_type", "free") == "refundable" else "样品申请"
    return {
        "schema": "2.0",
        "config": {
            "width_mode": "compact",
            "enable_forward": False,
            "update_multi": True,
        },
        "header": {
            "template": _header_template(task.platform_status),
            "title": {
                "tag": "plain_text",
                "content": f"TikTok {title} · {status}",
            },
        },
        "body": {
            "direction": "vertical",
            "vertical_spacing": "8px",
            "padding": "12px",
            "elements": elements,
        },
    }


def _test_banner() -> dict[str, object]:
    return markdown("🧪 **测试消息** · 当前不会发送给真实 BD")


def _identity(task, username: str | None, img_key: str | None) -> dict[str, object]:
    name = escape_text(task.creator_name, limit=80)
    identity = escape_text(f"@{username}" if username else "TikTok 达人", limit=80)
    level = escape_text(_optional_text(task.creator_level) or "未分级", limit=24)
    content = (
        f"👤 **{name}**　`{level}`\n"
        f"{identity}　PPS **{_score(task.creator_pps)}**　"
        f"评分 **{_score(task.creator_rating)}**"
    )
    if brief := profile_brief(task.creator_profile_snapshot):
        content += f"\n{brief}"
    text = markdown(content)
    if not img_key:
        return text
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "12px",
        "vertical_align": "center",
        "columns": [
            {
                "tag": "column",
                "width": "48px",
                "elements": [
                    {
                        "tag": "img",
                        "img_key": img_key,
                        "alt": {"tag": "plain_text", "content": "达人头像"},
                        "preview": False,
                    }
                ],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [text],
            },
        ],
    }


def _decision_metrics(task) -> list[tuple[str, str]]:
    return [
        ("粉丝数", _compact_number(task.follower_count)),
        ("近 30 天 GMV", _money(task.creator_gmv_minor, task.creator_gmv_currency)),
        ("PPS", _score(task.creator_pps)),
        ("样品分", sample_score_summary(task.creator_profile_snapshot)),
        ("成交件数", _compact_number(task.creator_units_sold)),
        ("预计发布率", _percentage(task.creator_fulfillment_percentage)),
    ]


def _actions(record_url: str, username: str | None) -> list[dict[str, object]]:
    buttons = [open_url_button("打开飞书处理", record_url, primary=True)]
    if username:
        profile_url = f"https://www.tiktok.com/@{quote(username, safe='._-')}"
        buttons.append(open_url_button("查看达人主页", profile_url, primary=False))
    return buttons


def _data_note(task) -> dict[str, object]:
    values = [f"样品申请观测于 {_format_time(task.source_observed_at, compact=True)}"]
    if task.creator_profile_observed_at:
        values.append(
            "达人画像观测于 "
            + _format_time(task.creator_profile_observed_at, compact=True)
        )
        if window := profile_window_summary(task.creator_profile_snapshot):
            values.append(window)
    else:
        values.append("暂无附加画像数据")
    return {
        "tag": "div",
        "text": {
            "tag": "plain_text",
            "content": " · ".join(values),
            "text_size": "notation",
            "text_color": "grey",
        },
    }


def _header_template(status: str) -> str:
    if status == "PENDING":
        return "orange"
    if status in {"COMPLETED", "OPS_COMPLETED"}:
        return "green"
    if "CANCELLED" in status or status == "OPS_FAILED":
        return "grey"
    return "blue"


def _compact_number(value: int | None) -> str:
    if value is None:
        return "—"
    absolute = abs(value)
    if absolute >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿".replace(".0亿", "亿")
    if absolute >= 10_000:
        return f"{value / 10_000:.1f}万".replace(".0万", "万")
    return f"{value:,}"


def _money(value_minor: int | None, currency: str | None) -> str:
    if value_minor is None:
        return "—"
    amount = value_minor / 100
    symbol = {"USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£"}.get(
        (currency or "").upper(), f"{(currency or '').upper()} " if currency else ""
    )
    if abs(amount) >= 1_000_000:
        number = f"{amount / 1_000_000:.1f}M"
    elif abs(amount) >= 1_000:
        number = f"{amount / 1_000:.1f}K"
    else:
        number = f"{amount:,.2f}".rstrip("0").rstrip(".")
    return f"{symbol}{number}".replace(".0M", "M").replace(".0K", "K")


def _percentage(value: Decimal | None) -> str:
    return (
        f"{value.normalize()}%"
        if value is not None and value.is_finite() and 0 <= value <= 100
        else "—"
    )


def _score(value: Decimal | None) -> str:
    return (
        f"{value:.1f}/5"
        if value is not None and value.is_finite() and 0 <= value <= 5
        else "—"
    )


def _format_time(value: datetime | None, *, compact: bool = False) -> str:
    if value is None:
        return "未提供"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    local = value.astimezone(ZoneInfo("Asia/Shanghai"))
    suffix = "" if compact else "（北京时间）"
    return local.strftime("%Y-%m-%d %H:%M") + suffix


def _safe_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _valid_img_key(value: str) -> bool:
    return 1 <= len(value) <= 512 and not any(char.isspace() for char in value)


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
