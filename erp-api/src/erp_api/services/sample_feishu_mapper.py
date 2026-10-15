from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from erp_api.services.feishu_sample_record_index import SYNC_KEY_FIELD
from erp_api.services.sample_application_identity import display_creator_name
from erp_api.services.sample_feishu_source_repository import (
    SampleFeishuSourceRecord,
)
from erp_api.services.sample_remaining_display import sample_remaining_display
from erp_api.services.sample_shop_display import sample_shop_display_name
from erp_api.services.sample_type_policy import SAMPLE_TYPE_LABELS


def _milliseconds(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.astimezone(UTC).timestamp() * 1000)


def _score_out_of_five(value: Decimal | None) -> str:
    return f"{value:.1f}/5.0" if value is not None else ""


def _sample_score(snapshot: object) -> int | float | None:
    if not isinstance(snapshot, Mapping):
        return None
    sample_score = snapshot.get("sample_score")
    if not isinstance(sample_score, Mapping):
        return None
    raw = sample_score.get("overall")
    if raw in (None, ""):
        return None
    try:
        score = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not score.is_finite():
        return None
    if score == score.to_integral_value():
        return int(score)
    return float(score)


def _product_options(value: str | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return list(
        dict.fromkeys(item.strip() for item in value.split("、") if item.strip())
    )


def format_sample_time_left(expires_at: datetime | None, *, now: datetime) -> str:
    if expires_at is None:
        return ""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    remaining_seconds = int(
        (expires_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds()
    )
    if remaining_seconds <= 0:
        return "已过期"
    if remaining_seconds >= 86_400:
        return f"剩余 {remaining_seconds // 86_400} 天"
    total_minutes = max(1, remaining_seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"剩余 {hours} 小时 {minutes} 分"
    if hours:
        return f"剩余 {hours} 小时"
    return f"剩余 {minutes} 分"


def build_feishu_system_fields(
    record: SampleFeishuSourceRecord, *, synced_at: datetime
) -> dict[str, Any]:
    sync_key = f"{record.shop_id}:{record.platform_application_id}"
    fields: dict[str, Any] = {
        "样品申请": f"{record.shop_name}｜{record.platform_application_id}",
        "样品类型": SAMPLE_TYPE_LABELS[record.sample_type],
        SYNC_KEY_FIELD: sync_key,
        "申请编号": record.platform_application_id,
        "达人昵称": display_creator_name(
            record.creator_nickname, record.creator_username
        ),
        "达人账号": (
            "@" + record.creator_username.lstrip("@")
            if record.sample_type == "refundable" and record.creator_username
            else record.creator_username or ""
        ),
        "达人OpenID": record.creator_open_id or "",
        "所属平台": "TikTok Shop",
        "申请样品编号": record.sku_id or record.product_id or "",
        "申请数量": "1",
        "粉丝数": str(record.follower_count or 0),
        "30日GMV": (
            record.creator_gmv_minor / 100
            if record.creator_gmv_minor is not None
            else 0
        ),
        "GMV币种": record.creator_gmv_currency or "",
        "达人等级": record.creator_level or "",
        "30日内容数": record.creator_content_count,
        "平均视频播放量": record.creator_ec_video_view,
        "样品履约率": (
            float(record.creator_fulfillment_percentage / Decimal(100))
            if record.creator_fulfillment_percentage is not None
            else None
        ),
        "30日销量": record.creator_units_sold,
        "PPS": _score_out_of_five(record.creator_pps),
        "达人评分": _score_out_of_five(record.creator_rating),
        "样品评分": _sample_score(record.creator_profile_snapshot),
        "TK申请状态": record.platform_status,
        "店铺标识": sample_shop_display_name(record.shop_name),
        "商品ID": _product_options(record.product_id),
        "商品名称": record.product_title or "",
        "SKU ID": record.sku_id or "",
        "SKU名称": record.sku_name or "",
        "通知状态": "待通知",
        "数据来源": record.source_type,
        "首次发现时间": _milliseconds(record.first_seen_at),
        "TikTok申请时间": (
            _milliseconds(record.tiktok_applied_at)
            if record.tiktok_applied_at is not None
            else None
        ),
        "样品申请剩余时间": "不适用（买返样品）" if record.sample_type == "refundable" else sample_remaining_display(
            status=record.platform_status,
            is_current=True,
            deadline=record.approve_expiration_at,
            now=synced_at,
            format_time=format_sample_time_left,
        ),
        "首次同步时间": _milliseconds(synced_at),
        "最近同步时间": _milliseconds(synced_at),
        "同步版本": 1,
        "ERP回写状态": "待回写",
    }
    if record.creator_username:
        profile_url = f"https://www.tiktok.com/@{record.creator_username}"
        fields["达人主页链接"] = {"link": profile_url, "text": profile_url}
    return fields
