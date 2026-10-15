from __future__ import annotations

from dataclasses import dataclass

from erp_api.services.feishu_sample_errors import FeishuSampleError

BUSINESS_FIELDS = frozenset({"分配BD", "处理状态", "处理结果", "备注"})
SYSTEM_FIELDS = frozenset(
    {
        "样品申请",
        "样品类型",
        "同步键（系统）",
        "申请编号",
        "首次发现时间",
        "TikTok申请时间",
        "样品申请剩余时间",
        "达人昵称",
        "达人账号",
        "达人OpenID",
        "达人主页链接",
        "所属平台",
        "申请样品编号",
        "申请数量",
        "粉丝数",
        "30日GMV",
        "GMV币种",
        "达人等级",
        "30日内容数",
        "平均视频播放量",
        "样品履约率",
        "30日销量",
        "PPS",
        "达人评分",
        "样品评分",
        "TK申请状态",
        "店铺标识",
        "商品ID",
        "商品名称",
        "SKU ID",
        "SKU名称",
        "数据来源",
        "分配时间",
        "通知状态",
        "通知时间",
        "首次同步时间",
        "最近同步时间",
        "同步版本",
        "ERP回写状态",
    }
)
REQUIRED_SAMPLE_FIELDS = SYSTEM_FIELDS | BUSINESS_FIELDS


@dataclass(frozen=True)
class FeishuFieldMetadata:
    field_id: str
    field_name: str
    field_type: int
    is_primary: bool
    ui_type: str | None = None
    field_property: dict[str, object] | None = None


def parse_feishu_field_metadata(item: object) -> FeishuFieldMetadata:
    if not isinstance(item, dict):
        raise FeishuSampleError("Feishu field metadata item is invalid.")
    field_id = item.get("field_id")
    field_name = item.get("field_name")
    field_type = item.get("type")
    is_primary = item.get("is_primary")
    ui_type = item.get("ui_type")
    field_property = item.get("property")
    if (
        not isinstance(field_id, str)
        or not field_id
        or not isinstance(field_name, str)
        or not field_name
        or isinstance(field_type, bool)
        or not isinstance(field_type, int)
        or not isinstance(is_primary, bool)
        or (ui_type is not None and not isinstance(ui_type, str))
        or (field_property is not None and not isinstance(field_property, dict))
    ):
        raise FeishuSampleError("Feishu field metadata item is invalid.")
    return FeishuFieldMetadata(
        field_id,
        field_name,
        field_type,
        is_primary,
        ui_type,
        dict(field_property) if isinstance(field_property, dict) else None,
    )
