from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from urllib.parse import urlsplit

from playwright.async_api import Page

from app.parsers.xlsx_worksheet_reader import read_first_worksheet
from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_video_export_download import (
    delete_download,
    download_video_export,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery

_MAX_RECONCILIATION_PAGES = 100
_PAGE_DELAY_MS = 3_000
_REVERSE_SET_SCRIPT = """async ({url, headers, body, pages, expectedTotal, delayMs}) => {
    const ids = new Set();
    const counts = [];
    for (let page = 1; page <= pages; page += 1) {
        body.params.video_list_params_v2[0].page_param.page_no = page;
        let response;
        let payload;
        for (let attempt = 0; attempt < 2; attempt += 1) {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 30000);
            try {
                response = await fetch(url, {
                    method: 'POST', headers, credentials: 'include',
                    body: JSON.stringify(body), signal: controller.signal,
                });
                payload = await response.json();
                break;
            } catch {
                if (attempt === 0) {
                    await new Promise(resolve => setTimeout(resolve, delayMs));
                }
            } finally {
                clearTimeout(timeout);
            }
        }
        if (!response || response.status !== 200 ||
            ![0, '0'].includes(payload?.code)) {
            return {accepted: false, reason: 'reverse_response_failed', page};
        }
        const segment = payload?.data?.video_list_segments_v2?.[0];
        if (segment?.total !== expectedTotal) {
            return {accepted: false, reason: 'reverse_total_changed', page};
        }
        const rows = Array.isArray(segment?.video_performances)
            ? segment.video_performances : [];
        counts.push(rows.length);
        for (const row of rows) {
            const id = String(row?.video_info?.item_id || '');
            if (id) ids.add(id);
        }
        if (page < pages) {
            await new Promise(resolve => setTimeout(resolve, delayMs));
        }
    }
    return {accepted: true, ids: Array.from(ids), counts};
}"""


async def verify_video_total_drift(
    page: Page,
    query: AffiliateCenterQuery,
    snapshot: Mapping[str, object],
    context: AffiliateAnalyticsResponseContext | None,
    forward_ids: frozenset[str],
) -> bool:
    prepared = _reconciliation_request(snapshot, context)
    if prepared is None:
        return False
    body, pages = prepared
    page_size = body["params"]["video_list_params_v2"][0]["page_param"]["page_size"]
    try:
        result = await page.evaluate(
            _REVERSE_SET_SCRIPT,
            {
                "url": context.request_url,
                "headers": dict(context.request_headers or {}),
                "body": body,
                "pages": pages,
                "expectedTotal": snapshot["expected_total"],
                "delayMs": _PAGE_DELAY_MS,
            },
        )
    except asyncio.CancelledError:
        capture_log("affiliate_video_drift_rejected", reason="reverse_cancelled")
        raise
    except Exception:  # noqa: BLE001 -- browser verification remains non-authoritative
        capture_log("affiliate_video_drift_rejected", reason="reverse_evaluation_failed")
        return False
    if not isinstance(result, Mapping) or result.get("accepted") is not True:
        reason = result.get("reason") if isinstance(result, Mapping) else None
        if reason not in {"reverse_response_failed", "reverse_total_changed"}:
            reason = "reverse_result_invalid"
        page_number = result.get("page") if isinstance(result, Mapping) else None
        capture_log(
            "affiliate_video_drift_rejected",
            reason=reason,
            page=page_number if isinstance(page_number, int) else None,
        )
        return False
    identifiers = result.get("ids")
    counts = result.get("counts")
    actual = snapshot.get("records_unique")
    reverse_matches = (
        isinstance(actual, int)
        and len(forward_ids) == actual
        and isinstance(identifiers, list)
        and all(isinstance(value, str) and value for value in identifiers)
        and len(identifiers) == actual
        and isinstance(counts, list)
        and len(counts) == pages
        and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= page_size
            for value in counts
        )
        and counts[-1] < page_size
        and sum(counts) == actual
        and frozenset(identifiers) == forward_ids
    )
    if not reverse_matches:
        capture_log(
            "affiliate_video_drift_rejected",
            reason="reverse_set_mismatch",
            forward_count=actual,
            reverse_count=len(identifiers) if isinstance(identifiers, list) else None,
            reverse_sum=sum(counts) if isinstance(counts, list)
            and all(isinstance(value, int) for value in counts) else None,
        )
        return False
    if not await _export_matches(page, query, forward_ids):
        capture_log("affiliate_video_drift_rejected", reason="export_unverified")
        return False
    return True


async def _export_matches(
    page: Page,
    query: AffiliateCenterQuery,
    forward_ids: frozenset[str],
) -> bool:
    download = None
    try:
        content, _, download, _ = await download_video_export(page, query)
        return _export_video_identifiers(content) == forward_ids
    except Exception:  # noqa: BLE001 -- failed evidence cannot confirm completeness
        return False
    finally:
        if download is not None:
            await delete_download(download)


def _export_video_identifiers(content: bytes) -> frozenset[str]:
    rows = iter(read_first_worksheet(content))
    headers = next(rows, None)
    if not isinstance(headers, list):
        return frozenset()
    matches = [
        index
        for index, value in enumerate(headers)
        if "".join(
            character for character in str(value).casefold() if character.isalnum()
        )
        == "videoid"
    ]
    if len(matches) != 1:
        return frozenset()
    column = matches[0]
    identifiers = [
        str(row[column]).strip()
        for row in rows
        if len(row) > column and row[column] is not None and str(row[column]).strip()
    ]
    if not identifiers or len(identifiers) != len(set(identifiers)):
        return frozenset()
    return frozenset(identifiers)


def _reconciliation_request(
    snapshot: Mapping[str, object],
    context: AffiliateAnalyticsResponseContext | None,
) -> tuple[dict[str, object], int] | None:
    if not _eligible(snapshot, context):
        return None
    body = copy.deepcopy(dict(context.request_body or {}))
    try:
        segment = body["params"]["video_list_params_v2"][0]
        page_param = segment["page_param"]
        sorter = segment["sorter"]
        page_number = page_param["page_no"]
        page_size = page_param["page_size"]
        order_type = sorter["order_type"]
    except (KeyError, IndexError, TypeError):
        return None
    expected = snapshot["expected_total"]
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or page_size <= 0
        or order_type not in (1, 2)
    ):
        return None
    pages = (expected + page_size - 1) // page_size
    if (
        pages < 1
        or pages > _MAX_RECONCILIATION_PAGES
        or page_number != pages
        or snapshot.get("last_page_index") != pages
        or snapshot.get("pages_fetched") != pages
    ):
        return None
    sorter["order_type"] = 2 if order_type == 1 else 1
    return body, pages


def _eligible(
    snapshot: Mapping[str, object],
    context: AffiliateAnalyticsResponseContext | None,
) -> bool:
    expected = snapshot.get("expected_total")
    actual = snapshot.get("records_unique")
    return (
        snapshot.get("status") == "partial"
        and snapshot.get("failure_category") == "total_count_mismatch"
        and isinstance(expected, int)
        and isinstance(actual, int)
        and 1 <= expected - actual <= 3
        and snapshot.get("records_received") == actual
        and snapshot.get("duplicates") == 0
        and snapshot.get("first_page_index") == 1
        and isinstance(snapshot.get("pages_fetched"), int)
        and snapshot.get("pages_fetched") == snapshot.get("last_page_index")
        and context is not None
        and urlsplit(context.request_url or "").hostname == "affiliate-us.tiktok.com"
        and isinstance(context.request_body, Mapping)
    )
