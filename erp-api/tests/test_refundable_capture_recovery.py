from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.services.sample_persistent_target import (
    PersistentSampleTarget,
    persistent_sample_key,
)
from scripts import sample_capture_priority as priority


def test_local_paid_keeps_its_dedicated_page_without_changing_free():
    shop = "9136806951995371293"
    assert persistent_sample_key(shop, "refundable") == (shop, "refundable")
    assert persistent_sample_key(shop, "free") is None


@pytest.mark.parametrize("shop", [
    "9622543325839925006", "9768147009521852682",
    "9121478993551097445", "9472478445887813622",
])
def test_cross_border_paid_reuses_approved_free_page_instead_of_opening_another(shop):
    assert persistent_sample_key(shop, "refundable") == (shop, "free")
    assert persistent_sample_key(shop, "free") == (shop, "free")


def test_local_paid_registry_accepts_only_the_local_affiliate_host(tmp_path):
    registry = PersistentSampleTarget(
        ("9136806951995371293", "refundable"), "ws://browser/local", root=tmp_path
    )
    registry.save("owned")
    target = {"id": "owned", "type": "page", "url":
              "https://affiliate-us.tiktok.com/affiliate/sample/sample-request?shop_id=9136806951995371293"}
    assert registry.resolve([target]) == "owned"
    target["url"] = target["url"].replace("affiliate-us.tiktok.com", "affiliate.tiktokshopglobalselling.com")
    with pytest.raises(RuntimeError, match="owned_page_target_changed"):
        registry.resolve([target])


@pytest.mark.parametrize("label", ["local", "cross-border-3", "cross-border-4", "cross-border-12"])
def test_paid_progress_waits_for_a_new_free_success_before_resuming(tmp_path, label):
    args = SimpleNamespace(status_dir=tmp_path, guard_root=tmp_path,
                           shop_label=label, tabs=[1, 2, 3])
    priority.finish_free(label, True, datetime.now(UTC) + timedelta(seconds=300), root=tmp_path)
    priority.mark_attempt(args, 3)
    priority.mark_paid_retry(args)
    assert priority.select_paid_tab(args) is None
    priority.finish_free(label, True, datetime.now(UTC) + timedelta(seconds=300), root=tmp_path)
    assert priority.select_paid_tab(args) == 3
    priority.finish_paid_retry(args, 3)
    assert priority.select_paid_tab(args) == 1
