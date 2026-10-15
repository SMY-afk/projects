from __future__ import annotations

from erp_api.services.sample_bd_invitation_ai_times import (
    AI_INVITATION_TIME_PENDING_REMARK,
)


def _unverified_ai_remark(non_ai_hits: tuple[str, ...], prior_remark: str) -> str:
    remark = AI_INVITATION_TIME_PENDING_REMARK
    if non_ai_hits:
        remark = f"命中：{'、'.join(non_ai_hits)}；已有BD合作，不重新自动分配；{remark}"
    if _was_bd_protected(prior_remark):
        marker = (
            "同轮新增，BD优先" if "同轮新增，BD优先" in prior_remark else "BD先提交"
        )
        remark += f"；{marker}（原保护凭证保留）"
    return remark


def _protection_remark(
    matched_sources: tuple[str, ...],
    available_sources: tuple[str, ...],
    unavailable_sources: tuple[str, ...],
) -> str:
    if matched_sources:
        assignment_note = (
            "已有BD合作，不重新自动分配"
            if "（每日更新）有效达人" in matched_sources
            else "按原有前置规则判断是否可分配"
        )
        return (
            f"命中：{'、'.join(matched_sources)}；"
            f"{assignment_note}；按创建时间保存24小时"
        )
    parts = []
    if available_sources:
        parts.append(f"未命中：{'、'.join(available_sources)}")
    else:
        parts.append("未命中配置的数据源")
    if unavailable_sources:
        parts.append(f"{'、'.join(unavailable_sources)}待接入")
    parts.append("保护原BD归属")
    parts.append("按创建时间保存7天")
    return "；".join(parts)


def _was_bd_protected(remark: str) -> bool:
    return (
        "BD先提交" in remark
        or "同轮新增，BD优先" in remark
        or (
            remark.startswith(("未命中：", "未命中配置的数据源"))
            and "保护原BD归属" in remark
            and "按创建时间保存7天" in remark
        )
    )
