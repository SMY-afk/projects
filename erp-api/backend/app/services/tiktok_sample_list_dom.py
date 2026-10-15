from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By

from backend.app.services.tiktok_sample_creator_details_collector import (
    SAMPLE_REQUEST_PATH,
)
from erp_api.services.affiliate_creator_summary_parser import (
    CreatorSummaryPayload,
    merge_profile_snapshots,
)
from erp_api.services.sample_notification_profile_builder import (
    REQUIRED_CREATOR_DETAIL_SOURCES,
)

SAMPLE_SCORE_HEADER = "Sample score"
_EMPTY_SCORE_VALUES = frozenset({"", "-", "--", "N/A"})
_SCORE_PATTERN = re.compile(r"(?:0|[1-9]\d*)(?:\.\d+)?")


@dataclass(frozen=True)
class SampleListDomScore:
    overall: str
    display_value: str
    observed_at: datetime


def sample_list_score(
    driver,
    username: str,
    *,
    observed_at: datetime | None = None,
) -> SampleListDomScore | None:
    """Read a visible creator row by the exact TikTok table header label."""
    for attempt in range(3):
        try:
            return _sample_list_score_once(
                driver,
                username,
                observed_at=observed_at,
            )
        except StaleElementReferenceException:
            if attempt == 2:
                raise
            time.sleep(0.1)
    raise AssertionError("Unreachable sample score retry state.")


def _sample_list_score_once(
    driver,
    username: str,
    *,
    observed_at: datetime | None,
) -> SampleListDomScore | None:
    matches = []
    score_table_found = False
    normalized_username = username.strip().lstrip("@").casefold()
    for table in driver.find_elements(By.CSS_SELECTOR, "table"):
        if not table.is_displayed():
            continue
        headers = table.find_elements(By.CSS_SELECTOR, "thead th")
        score_indexes = [
            index
            for index, header in enumerate(headers)
            if header.is_displayed() and _visible_text(header) == SAMPLE_SCORE_HEADER
        ]
        if not score_indexes:
            continue
        score_table_found = True
        if len(score_indexes) != 1:
            raise RuntimeError("Sample score table header is ambiguous.")
        for row in table.find_elements(By.CSS_SELECTOR, "tbody tr"):
            if (
                row.is_displayed()
                and normalized_username in _visible_text(row).casefold()
            ):
                matches.append((row, score_indexes[0]))
    if not score_table_found:
        return None
    if len(matches) != 1:
        raise RuntimeError("Sample score creator row is missing or ambiguous.")
    row, score_index = matches[0]
    cells = row.find_elements(By.CSS_SELECTOR, ":scope > td, :scope > th")
    if score_index >= len(cells) or not cells[score_index].is_displayed():
        raise RuntimeError("Sample score cell is missing or hidden.")
    display_value = _visible_text(cells[score_index])
    overall = _score_value(display_value)
    if overall is None:
        return None
    return SampleListDomScore(
        overall=overall,
        display_value=display_value,
        observed_at=observed_at or datetime.now(UTC),
    )


def sample_score_persistence_items(
    summaries: Sequence[tuple[CreatorSummaryPayload, object]],
    score: SampleListDomScore | None,
) -> list[tuple[CreatorSummaryPayload, str, str]]:
    network_items = [
        (summary, response.request_id, urlsplit(response.url).path)
        for summary, response in summaries
    ]
    if score is None:
        return network_items
    kinds = {summary.resource_kind for summary, _response in summaries}
    if kinds != REQUIRED_CREATOR_DETAIL_SOURCES:
        raise ValueError("Sample score requires a complete creator details batch.")
    profile = next(
        summary for summary, _ in summaries if summary.resource_kind == "profile"
    )
    if not profile.creator_username:
        raise ValueError("Sample score creator username is missing.")
    score_snapshot = {"sample_score": {"overall": score.overall}}
    dom_item = sample_score_persistence_item(
        platform_creator_id=profile.platform_creator_id,
        creator_open_id=profile.creator_open_id,
        creator_username=profile.creator_username,
        score=score,
    )
    enriched_items = []
    for summary, response in summaries:
        if summary.resource_kind == "performance":
            summary = replace(
                summary,
                profile_snapshot=merge_profile_snapshots(
                    summary.profile_snapshot, score_snapshot
                ),
            )
        enriched_items.append(
            (summary, response.request_id, urlsplit(response.url).path)
        )
    return [dom_item, *enriched_items]


def sample_score_persistence_item(
    *,
    platform_creator_id: str,
    creator_username: str,
    score: SampleListDomScore,
    creator_open_id: str | None = None,
) -> tuple[CreatorSummaryPayload, str, str]:
    creator_id = platform_creator_id.strip()
    username = creator_username.strip().lstrip("@")
    if not creator_id or not username:
        raise ValueError("Sample score creator identity is incomplete.")
    if _score_value(score.display_value) != score.overall:
        raise ValueError("Sample score normalized value does not match its display.")
    summary = CreatorSummaryPayload(
        resource_kind="sample_list_dom",
        platform_creator_id=creator_id,
        creator_open_id=creator_open_id,
        creator_username=username,
        profile_snapshot={"sample_score": {"overall": score.overall}},
        raw_data={
            "source": "sample_request_table_dom",
            "header": SAMPLE_SCORE_HEADER,
            "display_value": score.display_value,
        },
        observed_at=score.observed_at,
    )
    request_id = f"sample-list-dom:{score.observed_at.isoformat()}"
    return summary, request_id, SAMPLE_REQUEST_PATH


def _visible_text(element) -> str:
    return " ".join(str(element.text or "").split())


def _score_value(value: str) -> str | None:
    if value.upper() in _EMPTY_SCORE_VALUES:
        return None
    if not _SCORE_PATTERN.fullmatch(value):
        raise ValueError("Sample score display value is not numeric.")
    try:
        score = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Sample score display value is invalid.") from exc
    if not Decimal(0) <= score <= Decimal(100):
        raise ValueError("Sample score display value is out of range.")
    return value
