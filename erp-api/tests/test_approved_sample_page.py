import pytest

from backend.app.services.sample_persistent_target import PersistentSampleTarget
from backend.app.services.sample_owned_cdp import owned_sample_cdp


def test_missing_approved_external_page_is_not_recreated(tmp_path):
    registry = PersistentSampleTarget(("shop-7", "free"), "ws://browser/one", root=tmp_path)
    registry.save("external", externally_owned=True)
    with pytest.raises(RuntimeError, match="approved_sample_page_missing"):
        registry.resolve([])
    assert registry.is_externally_owned()


def test_external_ownership_is_persisted(tmp_path):
    registry = PersistentSampleTarget(("shop-7", "free"), "ws://browser/one", root=tmp_path)
    registry.save("external", externally_owned=True)
    assert registry.resolve([{"id": "external", "type": "page", "url": "about:blank"}]) == "external"
    assert registry.is_externally_owned()
