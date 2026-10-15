from datetime import datetime

from erp_api.services.sample_application_mapper import STATUS_LABELS


def sample_remaining_display(
    *, status, is_current, deadline, now: datetime, format_time
):
    if status.startswith("REFUNDABLE_"):
        return STATUS_LABELS.get(status, "买返状态待核验（无免费审核倒计时）")
    if not is_current:
        return "已被合并或替代（历史申请）"
    if status == "PENDING":
        if deadline is None:
            return "待核验（缺少截止时间）"
        return format_time(deadline, now=now)
    if status == "AWAITING_SHIPMENT":
        return "已同意（待发货）"
    if status == "CONTENT_PENDING":
        return "已寄样（内容处理中）"
    return STATUS_LABELS.get(status, "待核验（申请状态未知）")
