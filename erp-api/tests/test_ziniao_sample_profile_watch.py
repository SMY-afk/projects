from datetime import UTC, datetime, timedelta
from uuid import uuid4

from scripts.run_ziniao_sample_profile_watch import (
    _ensure_sample_request_page,
    _refresh_targets,
)

NOW = datetime(2026, 9, 11, 3, tzinfo=UTC)


def test_refresh_targets_keep_active_profiles_current_after_notification_sent() -> None:
    stale_one = uuid4()
    stale_two = uuid4()
    fresh = uuid4()
    complete = {"schema_version": 2, "creator_details_complete": True}
    rows = (
        (stale_one, "@Creator_Name", complete, NOW - timedelta(minutes=6)),
        (stale_two, "creator_name", {}, NOW),
        (fresh, "current_creator", complete, NOW - timedelta(minutes=1)),
    )

    targets = _refresh_targets(rows, now=NOW)

    assert len(targets) == 1
    assert targets[0].username == "creator_name"
    assert targets[0].outbox_ids == frozenset({stale_one, stale_two})


def test_ensure_sample_request_page_reuses_exact_shop_page() -> None:
    driver = _Driver(
        {
            "other": "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
            "?shop_id=other-shop",
            "sample": "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
            "?shop_id=target-shop",
        }
    )

    assert _ensure_sample_request_page(driver, "target-shop") == "sample"
    assert driver.created == []


def test_ensure_sample_request_page_prefers_current_matching_duplicate() -> None:
    driver = _Driver(
        {
            "sample-old": "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
            "?shop_id=target-shop",
            "sample-current": "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
            "?shop_id=target-shop",
        }
    )
    driver.current = "sample-current"

    assert _ensure_sample_request_page(driver, "target-shop") == "sample-current"
    assert driver.created == []


def test_ensure_sample_request_page_creates_dedicated_tab_when_missing() -> None:
    driver = _Driver(
        {"existing": "https://affiliate-us.tiktok.com/data/creator-analysis"}
    )

    handle = _ensure_sample_request_page(driver, "target-shop")

    assert handle == "created-1"
    assert driver.created == ["created-1"]
    assert driver.urls["existing"].endswith("/data/creator-analysis")
    assert driver.urls["created-1"] == (
        "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
        "?shop_id=target-shop"
    )


class _SwitchTo:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.current = handle

    def new_window(self, _kind):
        handle = f"created-{len(self.driver.created) + 1}"
        self.driver.created.append(handle)
        self.driver.urls[handle] = "about:blank"
        self.driver.current = handle


class _Driver:
    def __init__(self, urls):
        self.urls = dict(urls)
        self.current = next(iter(self.urls))
        self.created = []
        self.switch_to = _SwitchTo(self)

    @property
    def window_handles(self):
        return list(self.urls)

    @property
    def current_url(self):
        return self.urls[self.current]

    @property
    def current_window_handle(self):
        return self.current

    def get(self, url):
        self.urls[self.current] = url

    def close(self):
        del self.urls[self.current]
