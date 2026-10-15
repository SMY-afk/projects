import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.services.refundable_profile_cache import RefundableProfileCache


def rows(now, *, creator="creator-id", kinds=range(1, 6)):
    return [
        {
            "request": {"creator_oec_id": creator, "profile_types": [kind]},
            "payload": {"code": 0, "data": {}},
            "observed_at": now.isoformat(),
        }
        for kind in kinds
    ]


def test_cache_is_bound_to_shop_creator_and_account(tmp_path):
    now = datetime.now(UTC)
    cache = RefundableProfileCache(root=tmp_path)
    assert cache.save("shop-7", "creator-id", "creator.name", rows(now), now=now)
    assert len(cache.load("shop-7", "creator-id", "CREATOR.NAME", now=now)) == 5
    assert cache.load("shop-3", "creator-id", "creator.name", now=now) is None
    assert cache.load("shop-7", "another-id", "creator.name", now=now) is None
    assert cache.load("shop-7", "creator-id", "another.name", now=now) is None


def test_expired_profiles_are_not_reused_and_file_is_retained(tmp_path):
    now = datetime.now(UTC)
    cache = RefundableProfileCache(root=tmp_path)
    assert cache.save("shop-7", "creator-id", "creator.name", rows(now), now=now)
    assert (
        cache.load(
            "shop-7", "creator-id", "creator.name", now=now + timedelta(seconds=901)
        )
        is None
    )
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize("case", ["incomplete", "wrong_id", "future", "invalid_code"])
def test_invalid_source_profiles_are_not_cached(tmp_path, case):
    now = datetime.now(UTC)
    result = rows(now)
    if case == "incomplete":
        result.pop()
    if case == "wrong_id":
        result[0]["request"]["creator_oec_id"] = "another-id"
    if case == "future":
        result[0]["observed_at"] = (now + timedelta(minutes=1)).isoformat()
    if case == "invalid_code":
        result[0]["payload"]["code"] = False
    assert not RefundableProfileCache(root=tmp_path).save(
        "shop-7", "creator-id", "creator.name", result, now=now
    )
    assert not list(tmp_path.glob("*.json"))


def test_changed_profile_cache_fails_integrity_check(tmp_path):
    now = datetime.now(UTC)
    cache = RefundableProfileCache(root=tmp_path)
    assert cache.save("shop-7", "creator-id", "creator.name", rows(now), now=now)
    file = next(tmp_path.glob("*.json"))
    data = json.loads(file.read_text(encoding="utf-8"))
    data["profiles"][0]["payload"]["data"]["gmv"] = 9999
    file.write_text(json.dumps(data), encoding="utf-8")
    assert cache.load("shop-7", "creator-id", "creator.name", now=now) is None
