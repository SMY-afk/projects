"""Exact local free-sample metadata scope; never relax business prerequisites."""

import json
from datetime import UTC, datetime

LOCAL_TENANT = "6d0032eb-6a58-5a93-a819-d55c2a1c2e26"
LOCAL_SHOP = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"
PLATFORM_SHOP = "9136806951995371293"
RECEIPT_SOURCE = "tiktok_ziniao_metadata_bridge"
RECEIPT_EVENT = "local_sample_metadata_bridge_applied"
PAGE_KEYS = frozenset({"page", "page_num", "page_no", "page_index", "current_page", "cur_page"})
CURSOR_KEYS = frozenset({"cursor", "page_token", "next_page_token", "offset", "start"})


def account(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return None
    result = value.removeprefix("@").casefold()
    return result if result and "@" not in result else None


def fresh(value, now, seconds=900):
    return (isinstance(value, datetime) and value.utcoffset() is not None
            and 0 <= (now - value).total_seconds() <= seconds)


def eligible_candidate(app, workflow, batch, now, activation, *, allow_applied_marker=False):
    raw = app.raw_payload if isinstance(app.raw_payload, dict) else {}
    return (
        str(app.tenant_id) == LOCAL_TENANT and str(app.shop_id) == LOCAL_SHOP
        and app.source_type == "official_api" and app.sample_type == "free"
        and app.platform_status == "PENDING" and app.is_current_projection is True
        and app.is_approvable is True and isinstance(app.approve_expiration_at, datetime)
        and app.approve_expiration_at.utcoffset() is not None
        and app.approve_expiration_at > now
        and (raw.get("is_proactive_invitation") is None or allow_applied_marker
             and type(raw.get("is_proactive_invitation")) is bool)
        and raw.get("manual_assignment_deleted") is not True
        and account(app.creator_username) is not None and bool(app.creator_open_id)
        and workflow.assigned_bd_name is None and workflow.assignment_version == 0
        and isinstance(activation, datetime) and activation.utcoffset() is not None
        and app.first_seen_at >= activation and fresh(app.source_observed_at, now)
        and batch is not None and str(batch.tenant_id) == LOCAL_TENANT
        and str(batch.shop_id) == LOCAL_SHOP and batch.source_type == "official_api"
        and batch.sample_type == "free" and batch.status == "complete"
        and fresh(batch.finished_at, now) and batch.page_count > 0
        and (batch.expected_total is None or batch.expected_total == batch.captured_total)
    )


def require_manifest(manifest):
    if (manifest.get("tenant_id") != LOCAL_TENANT or manifest.get("shop_id") != LOCAL_SHOP
            or not isinstance(manifest.get("rows"), list) or not manifest["rows"]):
        raise RuntimeError("metadata_manifest_scope_invalid")
    targets = {row["platform_application_id"]: row for row in manifest["rows"]}
    if (len(targets) != len(manifest["rows"])
            or len({row["id"] for row in targets.values()}) != len(targets)
            or any(not account(row.get("creator_username")) for row in targets.values())):
        raise RuntimeError("metadata_manifest_identity_invalid")
    return targets


def require_initial_cursor(cursor):
    """Validate real request-body markers without a newer server-image dependency."""
    try:
        markers = json.loads(cursor)
        if not isinstance(markers, list) or not markers:
            raise TypeError("Invalid initial cursor markers")
        has_page = False
        for marker in markers:
            if not isinstance(marker, list) or len(marker) != 2 or not isinstance(marker[0], str):
                raise TypeError("Invalid initial cursor marker")
            key, value = marker[0].rsplit(".", 1)[-1], marker[1]
            if key in PAGE_KEYS:
                if type(value) is not int or value != 1:
                    raise ValueError("Initial cursor is not page one")
                has_page = True
            elif key in CURSOR_KEYS:
                if not (value is None or type(value) is int and value == 0
                        or isinstance(value, str) and value in {"", "0"}):
                    raise ValueError("Initial cursor is not empty")
            else:
                raise ValueError("Unknown initial cursor marker")
        if not has_page:
            raise ValueError("Initial cursor lacks page-one evidence")
    except (ValueError, TypeError) as error:
        raise RuntimeError("metadata_capture_pagination_incomplete") from error


def capture_scope(manifest, capture, *, now=None):
    now = now or datetime.now(UTC)
    targets = require_manifest(manifest)
    if (capture.get("shop_id") != LOCAL_SHOP or capture.get("platform_shop_id") != PLATFORM_SHOP
            or not capture.get("environment_id") or capture.get("tab") != 10
            or capture.get("sort") != "request_date"
            or capture.get("pagination_complete") is not True
            or capture.get("terminal_confirmed") is not True):
        raise RuntimeError("metadata_capture_scope_invalid")
    observed = datetime.fromisoformat(capture["observed_at"])
    if not fresh(observed, now):
        raise RuntimeError("metadata_capture_stale")
    pages, groups = capture.get("pages"), capture.get("applications")
    if (not isinstance(pages, list) or not pages or type(capture.get("page_count")) is not int
            or capture["page_count"] != len(pages)
            or any(not isinstance(page, dict) or type(page.get("page")) is not int for page in pages)
            or [page.get("page") for page in pages] != list(range(1, len(pages) + 1))
            or any(page.get("has_more") is not True for page in pages[:-1])
            or pages[-1].get("has_more") is not False
            or any(not isinstance(page.get("request_id"), str) or not page["request_id"].strip()
                   or not isinstance(page.get("cursor"), str) or not page["cursor"].strip() for page in pages)
            or len({page["request_id"] for page in pages}) != len(pages)
            or len({page["cursor"] for page in pages}) != len(pages)
            or not capture.get("request_id")):
        raise RuntimeError("metadata_capture_pagination_incomplete")
    require_initial_cursor(pages[0]["cursor"])
    total, expected = capture.get("captured_total"), capture.get("expected_total")
    if (not isinstance(groups, list) or type(total) is not int or total != len(groups)
            or expected is not None and (type(expected) is not int or expected != total)):
        raise RuntimeError("metadata_capture_totals_inconsistent")
    selected, seen, group_ids, found = [], set(), set(), set()
    for group in groups:
        products = group.get("products")
        if not isinstance(products, list) or not products:
            raise RuntimeError("metadata_capture_group_incomplete")
        ids = {item["application_id"] for item in products}
        if (len(ids) != len(products) or seen & ids or group.get("id") in group_ids
                or group.get("id") not in ids or set(group.get("source_item_ids", ())) != ids):
            raise RuntimeError("metadata_capture_identity_duplicate_or_incomplete")
        seen.update(ids)
        group_ids.add(group["id"])
        if not ids & targets.keys():
            continue
        creator = account(group.get("creator", {}).get("username"))
        if (group.get("status") != "PENDING" or not creator
                or any(account(targets[key]["creator_username"]) != creator
                       for key in ids & targets.keys())):
            raise RuntimeError("metadata_capture_creator_changed")
        for item in products:
            if (type(item.get("application_source_type")) is not int
                    or type(item.get("is_proactive_invitation")) is not bool):
                raise RuntimeError("metadata_raw_invitation_missing")
            timestamp = item.get("application_time")
            if type(timestamp) is not int or not 0 < timestamp <= now.timestamp():
                raise RuntimeError("metadata_raw_request_date_missing")
        selected.append(group)
        found.update(ids & targets.keys())
    if found != targets.keys():
        raise RuntimeError("metadata_capture_candidates_missing")
    return selected, observed
