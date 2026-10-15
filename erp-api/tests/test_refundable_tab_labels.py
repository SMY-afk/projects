import re

import pytest

from backend.app.services.refundable_sample_capture import TAB_LABELS


@pytest.mark.parametrize("tab,label", [
    (1, "Ready to ship4"), (2, "Shipped7"),
    (3, "In progress222"), (3, "In-progress9"),
    (6, "Canceled"), (6, "Cancelled"),
    (3, "处理中42"), (6, "已取消"),
    (4, "已退款0"), (5, "未退款2"),
    (4, "已返款1"), (5, "未返款0"),
])
def test_paid_status_tabs_accept_observed_chinese_and_english(tab, label):
    assert re.match(TAB_LABELS[tab], label, re.IGNORECASE)
