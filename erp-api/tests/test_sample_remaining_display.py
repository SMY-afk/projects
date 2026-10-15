from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.sample_feishu_mapper import format_sample_time_left
from erp_api.services.sample_remaining_display import sample_remaining_display


@pytest.mark.parametrize(
    "status,expected",
    [
        ("CANCELLED", "已取消"),
        ("AWAITING_SHIPMENT", "已同意（待发货）"),
        ("SHIPPED", "已发货"),
        ("CONTENT_PENDING", "已寄样（内容处理中）"),
        ("COMPLETED", "已完成"),
        ("PENDING", "待核验（缺少截止时间）"),
        ("UNKNOWN_11", "待核验（申请状态未知）"),
    ],
)
def test_history_status_has_explicit_remaining_time_display(status, expected):
    assert (
        sample_remaining_display(
            status=status,
            is_current=True,
            deadline=None,
            now=datetime(2026, 10, 10, tzinfo=UTC),
            format_time=format_sample_time_left,
        )
        == expected
    )


def test_replaced_application_never_shows_active_countdown():
    now = datetime(2026, 10, 10, tzinfo=UTC)
    assert (
        sample_remaining_display(
            status="PENDING",
            is_current=False,
            deadline=now + timedelta(days=6),
            now=now,
            format_time=format_sample_time_left,
        )
        == "已被合并或替代（历史申请）"
    )
