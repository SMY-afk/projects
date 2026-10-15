from tests.test_sample_notification_card import _task
from erp_api.services.sample_notification_card import build_sample_notification_card


def test_paid_card_changes_title_but_keeps_existing_layout():
    template = "https://example.invalid/configure-resource"
    paid = build_sample_notification_card(
        _task(sample_type="refundable", platform_status="REFUNDABLE_CONTENT_PENDING",
              approve_expiration_at=None), template, is_test=False,
    )
    free = build_sample_notification_card(_task(), template, is_test=False)
    assert paid["header"]["title"]["content"] == "TikTok 买返样品申请 · 买返处理中"
    assert free["header"]["title"]["content"] == "TikTok 样品申请 · 待审核"
    assert paid["schema"] == free["schema"]
    assert paid["config"] == free["config"]
    assert "不适用免费审核倒计时" in str(paid)
