from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as Row

import pytest

from scripts.local_sample_metadata_rules import (
    LOCAL_SHOP,
    LOCAL_TENANT,
    PLATFORM_SHOP,
    capture_scope,
    eligible_candidate,
)


def evidence(now):
    manifest = {"tenant_id": LOCAL_TENANT, "shop_id": LOCAL_SHOP,
                "rows": [{"id": "db-one", "platform_application_id": "one",
                          "creator_username": "@alice"}]}
    product = {"application_id": "one", "application_time": int(now.timestamp()) - 60,
               "application_source_type": 1, "is_proactive_invitation": False}
    group = {"id": "one", "status": "PENDING", "creator": {"username": "alice"},
             "source_item_ids": ["one"], "products": [product]}
    capture = {"shop_id": LOCAL_SHOP, "platform_shop_id": PLATFORM_SHOP,
               "environment_id": "verified", "observed_at": now.isoformat(),
               "page_count": 1, "expected_total": 1, "captured_total": 1,
               "pagination_complete": True, "terminal_confirmed": True,
               "tab": 10, "sort": "request_date", "request_id": "req-1",
               "pages": [{"page": 1, "cursor": '[["cur_page",1]]', "request_id": "req-1",
                          "has_more": False}], "applications": [group]}
    return manifest, capture


def candidate(now):
    app = Row(tenant_id=LOCAL_TENANT, shop_id=LOCAL_SHOP, source_type="official_api",
              sample_type="free", platform_status="PENDING", is_current_projection=True,
              is_approvable=True, approve_expiration_at=now + timedelta(days=1),
              raw_payload={}, first_seen_at=now, source_observed_at=now,
              creator_username="@alice", creator_open_id="creator-1")
    workflow = Row(assigned_bd_name=None, assignment_version=0)
    batch = Row(tenant_id=LOCAL_TENANT, shop_id=LOCAL_SHOP, source_type="official_api",
                sample_type="free", status="complete", finished_at=now,
                expected_total=1, captured_total=1, page_count=1)
    return app, workflow, batch


def test_only_truly_missing_marker_eligible():
    now = datetime.now(UTC)
    app, workflow, batch = candidate(now)
    assert eligible_candidate(app, workflow, batch, now, now - timedelta(days=1))
    for marker in (False, True, "false", 0):
        app.raw_payload = {"is_proactive_invitation": marker}
        assert not eligible_candidate(app, workflow, batch, now, now - timedelta(days=1))


@pytest.mark.parametrize("field,value", [
    ("sample_type", "refundable"), ("platform_status", "CANCELLED"),
    ("is_current_projection", False), ("is_approvable", False),
    ("creator_username", "Alice Smith"), ("creator_open_id", None),
])
def test_candidate_scope_fail_closed(field, value):
    now = datetime.now(UTC)
    app, workflow, batch = candidate(now)
    setattr(app, field, value)
    assert not eligible_candidate(app, workflow, batch, now, now - timedelta(days=1))


def test_running_source_and_stale_source_do_not_pass():
    now = datetime.now(UTC)
    app, workflow, batch = candidate(now)
    batch.status = "running"
    assert not eligible_candidate(app, workflow, batch, now, now - timedelta(days=1))
    batch.status = "complete"
    app.source_observed_at = now - timedelta(seconds=901)
    assert not eligible_candidate(app, workflow, batch, now, now - timedelta(days=1))


def test_capture_selects_only_matching_group_without_discarding_full_window():
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    groups, observed = capture_scope(manifest, capture, now=now)
    assert groups == capture["applications"]
    assert observed == now


@pytest.mark.parametrize("field,value", [
    ("tab", 0), ("sort", "relevance"), ("terminal_confirmed", False),
    ("captured_total", 2), ("expected_total", 2), ("platform_shop_id", "other"),
])
def test_incomplete_or_foreign_capture_never_applies(field, value):
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture[field] = value
    with pytest.raises(RuntimeError):
        capture_scope(manifest, capture, now=now)


def test_raw_bool_is_never_guessed_and_duplicate_or_missing_page_rejected():
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture["applications"][0]["products"][0]["is_proactive_invitation"] = None
    with pytest.raises(RuntimeError, match="invitation"):
        capture_scope(manifest, capture, now=now)
    manifest, capture = evidence(now)
    capture["pages"][0]["page"] = 2
    with pytest.raises(RuntimeError, match="pagination"):
        capture_scope(manifest, capture, now=now)


@pytest.mark.parametrize("page", [True, 1.0, "1", None])
def test_page_marker_must_be_an_integer_not_boolean(page):
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture["pages"][0]["page"] = page
    with pytest.raises(RuntimeError, match="pagination"):
        capture_scope(manifest, capture, now=now)


def test_request_ids_cannot_be_repeated_across_pages():
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture["page_count"] = 2
    capture["pages"][0]["has_more"] = True
    capture["pages"].append({"page": 2, "cursor": '[["cur_page",2]]',
                             "request_id": "req-1", "has_more": False})
    with pytest.raises(RuntimeError, match="pagination"):
        capture_scope(manifest, capture, now=now)


@pytest.mark.parametrize("request_id", ["", "   ", 1, None])
def test_request_id_must_be_nonempty_string(request_id):
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture["pages"][0]["request_id"] = request_id
    with pytest.raises(RuntimeError, match="pagination"):
        capture_scope(manifest, capture, now=now)


@pytest.mark.parametrize("cursor", [
    "opaque-first", "1:1", '[["cur_page",2]]', '[["cursor","next"]]',
    '[["cur_page",true]]', '[["cur_page",1],["offset",20]]',
])
def test_initial_cursor_must_prove_actual_page_one(cursor):
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture["pages"][0]["cursor"] = cursor
    with pytest.raises(RuntimeError, match="pagination"):
        capture_scope(manifest, capture, now=now)


@pytest.mark.parametrize("cursor", [
    '[["cur_page",1]]', '[["pagination.page",1],["pagination.cursor",""]]',
    '[["page_num",1],["offset",0]]',
])
def test_real_page_one_protocol_remains_compatible(cursor):
    now = datetime.now(UTC)
    manifest, capture = evidence(now)
    capture["pages"][0]["cursor"] = cursor
    assert capture_scope(manifest, capture, now=now)[0] == capture["applications"]
