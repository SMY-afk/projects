from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.refundable_sample_parser import parse_refundable_sample_page
from erp_api.services.sample_feishu_source_repository import build_committed_sample_query
from erp_api.services.sample_type_policy import is_assignable_sample, sample_assignment_condition


def parse(username):
    return parse_refundable_sample_page(
        {"code": 0, "data": {"total_count": 2, "apply_records": [
            {"apply_id": "bad", "creator_id": "123", "creator_name": username,
             "creator_nick_name": "Never use display name", "status": 40,
             "product_id": "p", "main_order_id": "o"},
            {"apply_id": "good", "creator_id": "456", "creator_name": "@valid.account",
             "status": 40, "product_id": "p", "main_order_id": "o2"},
        ]}}, request={"tab_type": 3, "cur_page": 1, "page_size": 50, "search_param": {}},
        request_id="r1", observed_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("username", [None, "", "  ", "@", "bad account"])
def test_bad_username_is_retained_and_quarantined_without_losing_good_row(username):
    page = parse(username)
    assert page.total_count == len(page.applications) == 2
    bad, good = page.applications
    assert bad["creator"]["username"] is None
    assert bad["refundable_identity_quarantine"] == "creator_unique_username_invalid"
    assert bad["refundable_raw"]["creator_name"] == username
    assert good["creator"]["username"] == "valid.account"
    assert "refundable_identity_quarantine" not in good
    for item, allowed in ((bad, False), (good, True)):
        app = SimpleNamespace(sample_type="refundable", is_current_projection=True,
            platform_status=item["status"], raw_payload=item, source_observed_at=datetime.now(UTC))
        assert is_assignable_sample(app, now=datetime.now(UTC)) is allowed


def test_sql_write_and_assignment_paths_both_exclude_identity_quarantine():
    queries = [sample_assignment_condition(), build_committed_sample_query(
        tenant_id=uuid4(), shop_id=uuid4(), after_application_id=None, limit=200)]
    for query in queries:
        compiled = query.compile(dialect=postgresql.dialect())
        assert "refundable_identity_quarantine" in compiled.params.values()
        assert "creator_username" in str(compiled)


@pytest.mark.asyncio
async def test_quarantined_profile_does_not_open_browser_or_load_cache(monkeypatch):
    from backend.app.services.refundable_creator_profile_capture import _capture_profiles

    def forbidden(*args, **kwargs):
        pytest.fail("Quarantined account must never navigate or read profile cache")

    monkeypatch.setattr("backend.app.services.refundable_creator_profile_capture._profile_page", forbidden)
    cache = SimpleNamespace(load=forbidden, save=forbidden)
    result = await _capture_profiles("invalid", "shop", [parse("").applications[0]],
        host="invalid", profile_cache=cache)
    assert result == {}


def complete_batch():
    from erp_api.services.remote_sample_capture import RemoteSampleBatch, RemoteSamplePage
    pages = []
    for number in range(1, 6):
        records = [{"apply_id": str(index), "creator_id": str(index + 1000),
            "creator_name": "" if index == 120 else f"account{index}",
            "status": 40, "product_id": "p", "main_order_id": str(index)}
            for index in range((number - 1) * 50, min(number * 50, 224))]
        pages.append(RemoteSamplePage(payload={
            "refundable_response": {"code": 0, "data": {"total_count": 224, "apply_records": records}},
            "refundable_request": {"tab_type": 3, "cur_page": number, "page_size": 50, "search_param": {}},
        }, request_id=f"page-{number}", observed_at=datetime.now(UTC)))
    return RemoteSampleBatch(capture_id=uuid4(), shop_id=uuid4(), sample_type="refundable",
        environment_id="123456", platform_shop_id="shop", pages=pages)


def test_quarantine_keeps_all_224_items_and_five_page_proof():
    from erp_api.services.remote_sample_capture import parse_complete_batch
    pages, digest = parse_complete_batch(complete_batch())
    items = [item for page in pages for item in page.applications]
    assert len(items) == 224 and len(digest) == 64
    assert sum("refundable_identity_quarantine" in item for item in items) == 1


@pytest.mark.parametrize("fault", ["missing_page", "missing_terminal", "duplicate"])
def test_quarantine_does_not_relax_batch_integrity(fault):
    from erp_api.services.remote_sample_capture import parse_complete_batch
    batch = complete_batch()
    if fault == "missing_page":
        del batch.pages[2]
    elif fault == "missing_terminal":
        batch.pages.pop()
    else:
        batch.pages[2].payload["refundable_response"]["data"]["apply_records"][0]["apply_id"] = "0"
    with pytest.raises(ValueError):
        parse_complete_batch(batch)


@pytest.mark.asyncio
async def test_quarantine_blocks_pending_cooperation_notifications_too():
    from contextlib import asynccontextmanager
    from erp_api.services.sample_cooperation_repository import SampleCooperationRepository

    class Session:
        async def execute(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            assert "refundable_identity_quarantine" in compiled.params.values()
            return SimpleNamespace(all=lambda: [])

    @asynccontextmanager
    async def session():
        yield Session()

    repo = SampleCooperationRepository(SimpleNamespace(system_session_factory=session),
        activation_at=datetime.now(UTC), batch_limit=200)
    assert await repo.list_candidates(uuid4(), uuid4(), application_ids=None) == ()
    assert await repo.list_due_actions(uuid4(), uuid4()) == ()


@pytest.mark.asyncio
async def test_historical_projection_and_assignment_record_writers_also_quarantine():
    from contextlib import asynccontextmanager
    from erp_api.services.sample_auto_assignment_feishu_service import SampleAutoAssignmentFeishuService
    from erp_api.services.sample_assignment_record_service import SampleAssignmentRecordService

    class Session:
        async def execute(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            assert "refundable_identity_quarantine" in compiled.params.values()
            return SimpleNamespace(all=lambda: [])

    @asynccontextmanager
    async def session():
        yield Session()

    database = SimpleNamespace(system_session_factory=session)
    projection = SampleAutoAssignmentFeishuService(database, None)
    records = SampleAssignmentRecordService(database, None,
        activation_at=datetime.now(UTC), sample_type="refundable")
    assert await projection._list_targets(uuid4(), uuid4()) == ()
    assert await records._list_targets(uuid4(), uuid4(), None, None) == ()
