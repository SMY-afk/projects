from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.refundable_sample_parser import parse_refundable_sample_page
from erp_api.services.sample_application_repository import build_group_item_supersede_statement
from erp_api.services.sample_type_policy import is_assignable_sample, sample_assignment_condition


def raw_record(**overrides):
    return {
        "apply_id": "9893624411594225534", "main_order_id": "947453136418919357",
        "creator_id": "123456", "creator_name": " @Creator.Name ",
        "creator_nick_name": "Display name", "product_id": "product-1",
        "product_name": "Robot dog", "sku_id": "sku-1", "sku_desc": "White",
        "sku_image": "https://example.com/image.png", "status": 40,
        "modify_time": "1791387636155", "max_suspend_time_ms_str": "864000000",
        **overrides,
    }


def parse(records, **request_overrides):
    return parse_refundable_sample_page(
        {"code": 0, "data": {"apply_records": records, "total_count": len(records)}},
        request={"tab_type": 3, "cur_page": 1, "page_size": 50,
                 "search_param": {"main_order_id": ""}, **request_overrides},
        request_id="paid-request", observed_at=datetime.now(UTC),
    )


def test_paid_contract_retains_real_identity_without_inventing_approval():
    page = parse([raw_record()])
    item = page.applications[0]
    assert item["id"] == "9893624411594225534"
    assert item["sample_type"] == "refundable"
    assert item["status"] == "REFUNDABLE_CONTENT_PENDING"
    assert item["creator"]["creator_open_id"] == "123456"
    assert item["creator"]["username"] == "Creator.Name"
    assert item["is_approvable"] is None
    assert item["application_time"] is None
    assert item["approve_expiration_time"] is None
    assert page.next_page_token is None


@pytest.mark.parametrize("overrides", [
    {"tab_type": 0}, {"cur_page": 0}, {"search_param": {"main_order_id": "filtered"}},
])
def test_unverified_scope_is_rejected(overrides):
    with pytest.raises(ValueError):
        parse([raw_record()], **overrides)


def test_invalid_creator_id_rejects_batch_but_bad_username_is_quarantined():
    with pytest.raises(ValueError):
        parse([raw_record(creator_id="12 34")])
    item = parse([raw_record(creator_name="creator name")]).applications[0]
    assert item["refundable_identity_quarantine"] == "creator_unique_username_invalid"


@pytest.mark.parametrize("status,allowed", [
    ("REFUNDABLE_AWAITING_SHIPMENT", True), ("REFUNDABLE_SHIPPED", True),
    ("REFUNDABLE_CONTENT_PENDING", True), ("REFUNDABLE_REFUNDED", False),
    ("REFUNDABLE_NOT_REFUNDED", False), ("REFUNDABLE_CANCELLED", False),
])
def test_paid_eligibility_does_not_relax_free_approval_gate(status, allowed):
    application = SimpleNamespace(
        sample_type="refundable", platform_status=status, is_current_projection=True,
        is_approvable=None, approve_expiration_at=None,
        raw_payload={"refundable_contract_verified": True}, source_observed_at=datetime.now(UTC),
    )
    assert is_assignable_sample(application, now=datetime.now(UTC)) is allowed
    application.sample_type = "free"
    assert is_assignable_sample(application, now=datetime.now(UTC)) is False


def test_stale_paid_order_is_not_assignable():
    application = SimpleNamespace(
        sample_type="refundable", platform_status="REFUNDABLE_CONTENT_PENDING",
        is_current_projection=True, raw_payload={"refundable_contract_verified": True},
        source_observed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert not is_assignable_sample(application, now=datetime.now(UTC))


def test_query_and_group_replacement_are_type_isolated():
    statement = build_group_item_supersede_statement(
        tenant_id=uuid4(), shop_id=uuid4(), parent_application_id=uuid4(),
        parent_platform_application_id="1", source_item_ids=["1", "2"],
        creator_open_id="1234", sample_type="free",
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "sample_applications.sample_type" in str(compiled)
    assert "free" in compiled.params.values()
    sql = str(sample_assignment_condition().compile(dialect=postgresql.dialect()))
    assert "sample_type" in sql
