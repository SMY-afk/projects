import inspect

from backend.app.services.tiktok_sample_creator_details_selenium import (
    _capture_target,
    _sample_handle,
)


class _SwitchTo:
    def __init__(self, driver) -> None:
        self._driver = driver

    def window(self, handle) -> None:
        self._driver.current_window_handle = handle


class _Driver:
    def __init__(self, *, current: str) -> None:
        self.current_window_handle = current
        self.window_handles = ["sample-a", "creator", "sample-b", "sample-c"]
        self.urls = {
            "sample-a": (
                "https://affiliate-us.tiktok.com/affiliate/sample/"
                "sample-request?shop_id=shop-one"
            ),
            "creator": (
                "https://affiliate-us.tiktok.com/affiliate/assets/"
                "video-analysis?shop_id=shop-one"
            ),
            "sample-b": (
                "https://affiliate-us.tiktok.com/affiliate/sample/"
                "sample-request?shop_id=shop-one"
            ),
            "sample-c": (
                "https://affiliate-us.tiktok.com/affiliate/sample/"
                "sample-request?shop_id=shop-one"
            ),
        }
        self.switch_to = _SwitchTo(self)

    @property
    def current_url(self):
        return self.urls[self.current_window_handle]


def test_sample_handle_prefers_current_matching_page_when_duplicates_exist() -> None:
    driver = _Driver(current="sample-b")

    selected = _sample_handle(driver, "shop-one")

    assert selected == "sample-b"
    assert driver.current_window_handle == "sample-b"


def test_sample_handle_uses_first_matching_page_when_current_is_not_sample() -> None:
    driver = _Driver(current="creator")

    selected = _sample_handle(driver, "shop-one")

    assert selected == "sample-a"
    assert driver.current_window_handle == "sample-a"


def test_creator_detail_reload_uses_non_blocking_cdp_command() -> None:
    source = inspect.getsource(_capture_target)

    assert "driver.refresh()" not in source
    assert '"Page.reload"' in source
