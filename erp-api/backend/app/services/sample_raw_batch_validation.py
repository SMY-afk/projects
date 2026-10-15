from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Protocol

RAW_PAGE_KEYS = ("page", "page_num", "page_no", "page_index", "current_page", "cur_page")
RAW_CURSOR_KEYS = ("cursor", "page_token", "next_page_token", "offset", "start")


def validate_initial_cursor(cursor: str) -> None:
    if re.fullmatch(r"[1-6]:1", cursor):
        return
    try:
        markers = json.loads(cursor)
    except (TypeError, ValueError) as error:
        raise RuntimeError("RAW batch initial cursor is invalid") from error
    if not isinstance(markers, list) or not markers:
        raise RuntimeError("RAW batch initial cursor is invalid")
    has_page = False
    for marker in markers:
        if not isinstance(marker, list) or len(marker) != 2 or not isinstance(marker[0], str):
            raise RuntimeError("RAW batch initial cursor is invalid")
        key, value = marker[0].rsplit(".", 1)[-1], marker[1]
        if key in RAW_PAGE_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or value != 1:
                raise RuntimeError("RAW batch initial cursor is invalid")
            has_page = True
        elif key in RAW_CURSOR_KEYS:
            if isinstance(value, bool) or value not in (None, "", 0, "0"):
                raise RuntimeError("RAW batch initial cursor is invalid")
        else:
            raise RuntimeError("RAW batch initial cursor is invalid")
    if not has_page:
        raise RuntimeError("RAW batch initial cursor is invalid")


class StoredPage(Protocol):
    request_id: str
    request_page: int | None
    request_cursor: str
    response_has_more: bool
    response_total_count: int | None


def validate_stored_raw_pages(
    pages: Sequence[StoredPage],
    *,
    expected_total: int | None,
    captured_total: int,
    terminal_confirmed: bool,
) -> int | None:
    if not pages:
        raise RuntimeError("RAW batch has no pages")
    if any(not isinstance(page.response_has_more, bool) for page in pages):
        raise RuntimeError("RAW batch has_more is missing or invalid")
    request_ids = [page.request_id for page in pages]
    cursors = [page.request_cursor for page in pages]
    request_pages = [page.request_page for page in pages]
    if len(request_ids) != len(set(request_ids)):
        raise RuntimeError("RAW batch contains a duplicate request id")
    if len(cursors) != len(set(cursors)):
        raise RuntimeError("RAW batch contains a duplicate cursor")
    if any(not isinstance(page, int) or isinstance(page, bool) for page in request_pages):
        raise RuntimeError("RAW batch request page marker is missing or invalid")
    if request_pages[0] != 1:
        raise RuntimeError("RAW batch first page must be 1")
    validate_initial_cursor(cursors[0])
    if request_pages != list(range(1, 1 + len(pages))):
        raise RuntimeError("RAW batch request pages are not contiguous")
    if (
        not terminal_confirmed
        or pages[-1].response_has_more
        or any(not page.response_has_more for page in pages[:-1])
    ):
        raise RuntimeError("RAW batch terminal page is not confirmed")
    response_totals = {
        page.response_total_count
        for page in pages
        if page.response_total_count is not None
    }
    if len(response_totals) > 1 or (
        expected_total is not None
        and response_totals
        and expected_total not in response_totals
    ):
        raise RuntimeError("RAW batch expected total changed")
    if expected_total is not None and expected_total != captured_total:
        raise RuntimeError("RAW batch captured total does not match")
    return next(iter(response_totals), None)
