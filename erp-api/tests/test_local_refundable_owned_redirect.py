"""Only a verified collector's local paid page may recover an official redirect."""

import pytest

from backend.app.services.sample_persistent_target import PersistentSampleTarget

LOCAL_SHOP = "9136806951995371293"
BROWSER = "ws://browser/local"


def registry(tmp_path, *, shop=LOCAL_SHOP, purpose="refundable", external=False):
    result = PersistentSampleTarget((shop, purpose), BROWSER, root=tmp_path)
    result.save("owned-local-paid", externally_owned=external)
    return result


def target(url):
    return [{"id": "owned-local-paid", "type": "page", "url": url}]


def test_exact_collector_owned_local_paid_landing_is_reusable(tmp_path):
    result = registry(tmp_path)
    assert result.resolve(target(
        "https://seller-us.tiktok.com/affiliate/landing"
    )) == "owned-local-paid"


def test_local_paid_landing_with_exact_shop_is_reusable(tmp_path):
    result = registry(tmp_path)
    assert result.resolve(target(
        f"https://seller-us.tiktok.com/affiliate/landing?shop_id={LOCAL_SHOP}"
    )) == "owned-local-paid"


@pytest.mark.parametrize("url", [
    "https://seller-us.tiktok.com/affiliate/landing?shop_id=another",
    "https://seller-us.tiktok.com/affiliate/landing?oec_seller_id=another",
    "https://seller-us.tiktok.com/affiliate/landing?shop_id=another&shop_id=9136806951995371293",
    "https://seller-us.tiktok.com/homepage",
    "https://seller-us.tiktok.com/login",
    "http://seller-us.tiktok.com/affiliate/landing",
    "https://seller-us.tiktok.com.evil.test/affiliate/landing",
    "https://seller-us.tiktok.com/affiliate/landing/extra",
])
def test_local_redirect_does_not_widen_domain_route_or_shop_scope(tmp_path, url):
    result = registry(tmp_path)
    with pytest.raises(RuntimeError, match="owned_page_(target|shop)_changed"):
        result.resolve(target(url))


@pytest.mark.parametrize("kwargs", [
    {"external": True},
    {"purpose": "free"},
    {"shop": "9121478993551097445"},
])
def test_redirect_recovery_never_adopts_external_free_or_other_shop(tmp_path, kwargs):
    result = registry(tmp_path, **kwargs)
    with pytest.raises(RuntimeError, match="owned_page_target_changed"):
        result.resolve(target("https://seller-us.tiktok.com/affiliate/landing"))


def test_recovery_does_not_adopt_new_browser_or_target(tmp_path):
    result = registry(tmp_path)
    result.browser = "0" * 64
    assert result.resolve(target("https://seller-us.tiktok.com/affiliate/landing")) is None
    result.browser = registry(tmp_path).browser
    assert result.resolve([{
        "id": "other", "type": "page",
        "url": "https://seller-us.tiktok.com/affiliate/landing",
    }]) is None
