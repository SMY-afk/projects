from datetime import date
from uuid import uuid4

from erp_api.services.sample_cooperation_rules import (
    CooperationCandidate,
    CooperationRecipient,
    CooperationRow,
    CooperationSnapshot,
    decide_cooperation,
)


def snapshot(shop):
    return CooperationSnapshot(rows=(), recipients={"bd": CooperationRecipient("BD", "ou_bd")},
        current_bd_names=frozenset({"bd"}), valid_creator_ids=frozenset({"abc"}),
        daily_valid_rows=(CooperationRow(shop, "r1", "@abc", "BD", None),))


def test_daily_ownership_matches_exact_shop_not_product_line():
    candidate = CooperationCandidate(uuid4(), "a1", "abc", "fanfu toy tool")
    own = decide_cooperation(candidate, snapshot("跨境3"), today=date(2026, 10, 14))
    other = decide_cooperation(candidate, snapshot("跨境7"), today=date(2026, 10, 14))
    assert own.reason == "active_creator_daily_bd_verified"
    assert other.reason == "not_registered"


def test_blank_shop_cannot_turn_into_global_ownership():
    candidate = CooperationCandidate(uuid4(), "a1", "abc", "fanfu toy tool")
    decision = decide_cooperation(candidate, snapshot(""), today=date(2026, 10, 14))
    assert decision.reason == "active_creator_shop_missing"


def test_confirmed_shop_owner_is_not_blocked_by_preserved_blank_history():
    from dataclasses import replace

    value = snapshot("跨境3")
    value = replace(value, daily_valid_rows=(*value.daily_valid_rows,
        CooperationRow("", "older", "abc", "BD", None)))
    candidate = CooperationCandidate(uuid4(), "a1", "abc", "fanfu toy tool")
    assert decide_cooperation(candidate, value, today=date(2026, 10, 14)).reason == "active_creator_daily_bd_verified"
