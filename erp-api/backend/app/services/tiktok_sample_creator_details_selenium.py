from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_creator_profile_performance_buffer import (
    CreatorSummaryPerformanceBuffer,
    captured_profile_types,
    response_profile_types,
)
from backend.app.services.tiktok_sample_creator_details_collector import (
    SAMPLE_REQUEST_PATH,
    SEARCH_SELECTOR,
    SampleCreatorDetailsTarget,
    creator_details_identity_matches,
)
from backend.app.services.tiktok_sample_list_dom import (
    sample_list_score,
    sample_score_persistence_items,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_creator_summary_parser import (
    discriminate_creator_summary,
    parse_creator_summary,
)
from erp_api.services.affiliate_creator_summary_repository import (
    AffiliateCreatorSummaryRepository,
)
from erp_api.services.sample_notification_profile_builder import (
    REQUIRED_CREATOR_DETAIL_SOURCES,
)


class TikTokSampleCreatorDetailsSeleniumCollector:
    def __init__(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        external_shop_id: str,
        database: Database,
        *,
        response_wait_seconds: float = 15,
    ) -> None:
        self._tenant_id = tenant_id
        self._shop_id = shop_id
        self._external_shop_id = external_shop_id
        self._repository = AffiliateCreatorSummaryRepository(database)
        self._response_wait_seconds = response_wait_seconds

    async def capture(
        self, driver, targets: Sequence[SampleCreatorDetailsTarget]
    ) -> int:
        if not targets:
            return 0
        sample_handle = _sample_handle(driver, self._external_shop_id)
        driver.switch_to.window(sample_handle)
        driver.execute_cdp_cmd("Network.enable", {})
        completed = 0
        try:
            for target_index, target in enumerate(targets):
                try:
                    responses, list_score = _capture_target(
                        driver,
                        sample_handle,
                        self._external_shop_id,
                        target.username,
                        self._response_wait_seconds,
                    )
                    summaries = _verified_summaries(
                        responses,
                        self._external_shop_id,
                        target.username,
                    )
                    items = sample_score_persistence_items(summaries, list_score)
                    await self._repository.persist_batch(
                        self._tenant_id,
                        self._shop_id,
                        items,
                    )
                    completed += 1
                except Exception as error:  # noqa: BLE001 -- isolate one target
                    capture_log(
                        "sample_creator_details_target_failed",
                        shop_id=self._shop_id,
                        target_index=target_index,
                        error_type=type(error).__name__,
                    )
        finally:
            driver.switch_to.window(sample_handle)
            _replace_search(driver, "")
        return completed


def _capture_target(driver, sample_handle, shop_id, username, timeout):
    driver.switch_to.window(sample_handle)
    driver.get_log("performance")
    _replace_search(driver, username)
    _wait_for_row(driver, username, timeout)
    list_score = sample_list_score(driver, username)
    handles = set(driver.window_handles)
    _click_creator_avatar(driver, username)
    detail_handle = _wait_for_detail_handle(driver, handles, shop_id, username, timeout)
    try:
        driver.switch_to.window(detail_handle)
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})
        driver.get_log("performance")
        driver.execute_cdp_cmd("Page.reload", {"ignoreCache": True})
        _wait_for_detail_identity(driver, shop_id, username, timeout)
        observed_at = datetime.now(UTC)
        buffer = CreatorSummaryPerformanceBuffer()
        captured = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            captured.extend(
                buffer.consume(
                    driver.get_log("performance"),
                    lambda request_id: driver.execute_cdp_cmd(
                        "Network.getResponseBody", {"requestId": request_id}
                    ),
                    observed_at=observed_at,
                )
            )
            if captured_profile_types(captured) == {1, 2, 3, 4, 5}:
                return captured, list_score
            time.sleep(0.1)
        captured_types = sorted(captured_profile_types(captured))
        raise TimeoutError(
            f"Creator details responses are incomplete: profile_types={captured_types}."
        )
    finally:
        if detail_handle in driver.window_handles:
            driver.switch_to.window(detail_handle)
            driver.close()
            driver.switch_to.window(sample_handle)


def _verified_summaries(responses, shop_id, username):
    summaries = []
    for response in sorted(
        responses, key=lambda item: min(response_profile_types(item))
    ):
        if platform_shop_id(response.url) != shop_id:
            raise ValueError("Creator details response shop does not match.")
        kind = discriminate_creator_summary(urlsplit(response.url).path)
        if kind is None:
            continue
        summary = parse_creator_summary(
            kind,
            response.payload,
            response.request_body,
            observed_at=response.observed_at,
        )
        if summary.creator_username is None:
            summary = replace(summary, creator_username=username)
        summaries.append((summary, response))
    kinds = {summary.resource_kind for summary, _response in summaries}
    creator_ids = {summary.platform_creator_id for summary, _response in summaries}
    normalized = username.strip().lstrip("@").casefold()
    names = {
        summary.creator_username.strip().lstrip("@").casefold()
        for summary, _response in summaries
        if summary.creator_username
    }
    if (
        kinds != REQUIRED_CREATOR_DETAIL_SOURCES
        or len(creator_ids) != 1
        or names != {normalized}
    ):
        raise ValueError("Creator details batch identity or completeness failed.")
    return summaries


def _sample_handle(driver, shop_id):
    matches = []
    original = driver.current_window_handle
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        split = urlsplit(driver.current_url)
        if split.path == SAMPLE_REQUEST_PATH and f"shop_id={shop_id}" in split.query:
            matches.append(handle)
    if not matches:
        raise RuntimeError("Sample requests page is missing.")
    selected = original if original in matches else matches[0]
    driver.switch_to.window(selected)
    return selected


def _replace_search(driver, value):
    search = driver.find_element(By.CSS_SELECTOR, SEARCH_SELECTOR)
    search.send_keys(Keys.CONTROL, "a")
    search.send_keys(Keys.BACKSPACE)
    if value:
        search.send_keys(value)
    search.send_keys(Keys.ENTER)


def _wait_for_row(driver, username, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        count = driver.execute_script(
            "const u=arguments[0];return [...document.querySelectorAll('tr')]"
            ".filter(r=>(r.innerText||'').toLowerCase().includes(u)).length;",
            username.casefold(),
        )
        if count == 1:
            return
        time.sleep(0.25)
    raise TimeoutError("Sample request creator row is missing or ambiguous.")


def _click_creator_avatar(driver, username):
    for attempt in range(3):
        avatar = driver.execute_script(
            "const u=arguments[0];const r=[...document.querySelectorAll('tr')]"
            ".find(r=>(r.innerText||'').toLowerCase().includes(u));"
            "return r?.querySelector('.pulse-avatar')||null;",
            username.casefold(),
        )
        if avatar is None:
            raise RuntimeError("Sample request creator avatar is missing.")
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", avatar
            )
            time.sleep(0.2)
            avatar.click()
            return
        except StaleElementReferenceException:
            if attempt == 2:
                raise
            time.sleep(0.1)


def _wait_for_detail_handle(driver, previous, shop_id, username, timeout):
    deadline = time.monotonic() + timeout
    candidate = None
    while time.monotonic() < deadline:
        added = set(driver.window_handles) - previous
        if len(added) == 1:
            candidate = next(iter(added))
            driver.switch_to.window(candidate)
            if creator_details_identity_matches(driver.current_url, shop_id, username):
                return candidate
        elif len(added) > 1:
            raise RuntimeError("Creator details page is ambiguous.")
        time.sleep(0.25)
    if candidate is not None and candidate in driver.window_handles:
        driver.switch_to.window(candidate)
        if creator_details_identity_matches(driver.current_url, shop_id, username):
            return candidate
    raise TimeoutError("Creator details page identity does not match.")


def _wait_for_detail_identity(driver, shop_id, username, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if creator_details_identity_matches(driver.current_url, shop_id, username):
            return
        time.sleep(0.25)
    raise TimeoutError("Creator details page identity changed during refresh.")
