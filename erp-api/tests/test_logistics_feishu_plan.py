from types import SimpleNamespace

import pytest

from erp_api.services.logistics_feishu_fields import (
    KEY_FIELD,
    RED,
    RESOLVED,
    STATE_FIELD,
    YELLOW,
)
from erp_api.services.logistics_feishu_plan import build_plan


def record(key, state=RED, fields=None):
    return SimpleNamespace(record_id="rec1", fields={KEY_FIELD: key, STATE_FIELD: state, **(fields or {})})


def test_resolves_same_record_preserving_first_seen_and_user_notes():
    prior = record("tenant:shop:order", fields={"首次接入飞书时间": "first", "BD备注": "keep"})
    plan = build_plan([{KEY_FIELD: "tenant:shop:order", STATE_FIELD: RESOLVED}], [prior], "tenant", "now")
    assert not plan["creates"]
    rid, patch = plan["updates"][0]
    assert rid == "rec1" and patch["解除预警时间"] == "now" and patch["首次接入飞书时间"] == "first"
    assert "BD备注" not in patch


def test_reentry_reuses_resolved_order_without_duplicates():
    prior = record("tenant:shop:order", RESOLVED, fields={"解除预警时间": "before", "首次接入飞书时间": "first"})
    plan = build_plan([{KEY_FIELD: "tenant:shop:order", STATE_FIELD: YELLOW}], [prior], "tenant", "now")
    assert not plan["creates"] and plan["updates"][0][1]["解除预警时间"] == ""


def test_unchanged_records_do_not_write_only_to_move_sync_time():
    prior = record("tenant:shop:order", fields={"首次接入飞书时间": "first", "解除预警时间": "", "最近飞书同步时间": "old"})
    assert build_plan([{KEY_FIELD: "tenant:shop:order", STATE_FIELD: RED, "最近飞书同步时间": "new"}],
                      [prior], "tenant", "now") == {"creates": [], "updates": []}


def test_reuses_only_completely_empty_placeholder_records():
    rows = [SimpleNamespace(record_id="empty", fields={}), SimpleNamespace(record_id="user", fields={"BD备注": "keep"})]
    plan = build_plan([{KEY_FIELD: "tenant:shop:order", STATE_FIELD: RED}], rows, "tenant", "now")
    assert plan["updates"][0][0] == "empty" and not plan["creates"]


@pytest.mark.parametrize("records", [[record("tenant:shop:order"), record("tenant:shop:order")], [record("other:shop:order")]])
def test_rejects_duplicate_or_other_tenant_keys(records):
    with pytest.raises(ValueError):
        build_plan([], records, "tenant", "now")


def test_missing_active_source_is_not_treated_as_resolved():
    with pytest.raises(ValueError, match="missing"):
        build_plan([], [record("tenant:shop:order")], "tenant", "now")
