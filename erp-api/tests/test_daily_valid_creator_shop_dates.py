from copy import deepcopy
from datetime import UTC, date, datetime

import pytest
from dateutil.relativedelta import relativedelta

from scripts.daily_valid_creator_core import desired_rows, validate_sources
from scripts.daily_valid_creator_dates import parse_shop_cutoffs
from scripts.daily_valid_creator_online import validate_online_evidence


def _cutoffs():
    return parse_shop_cutoffs(
        [
            "跨境3,2026-10-03,2026-10-02,2026-10-01",
            "跨境7,2026-10-02,2026-10-01,2026-09-30",
            "跨境4,2026-10-03,2026-10-02,2026-10-01",
            "跨境12,2026-10-01,2026-09-30,2026-09-29",
            "本土店,2026-10-03,2026-10-01,2026-09-30",
        ],
        today=date(2026, 10, 5),
    )


def test_cutoffs_require_five_unique_shops_and_allow_distinct_dates():
    cutoffs = _cutoffs()
    assert cutoffs["跨境7"]["creators"] == date(2026, 10, 2)
    assert cutoffs["跨境12"]["videos"] == date(2026, 9, 30)
    with pytest.raises(ValueError, match="five shops"):
        parse_shop_cutoffs(["跨境3,2026-10-03,2026-10-02,2026-10-01"])
    with pytest.raises(ValueError, match="duplicate"):
        parse_shop_cutoffs(
            ["跨境3,2026-10-03,2026-10-02,2026-10-01"] * 5,
            today=date(2026, 10, 5),
        )


def test_online_evidence_matches_each_shop_instead_of_global_date():
    cutoffs = _cutoffs()
    now = datetime(2026, 10, 5, 1, 30, tzinfo=UTC)
    evidence = {
        "source": "direct_tk_sources",
        "shops": [
            {
                "shop": name,
                "observed_at": now.isoformat(),
                "creators": str(dates["creators"]),
                "videos": str(dates["videos"]),
                "liveAccounts": str(dates["liveAccounts"]),
            }
            for name, dates in cutoffs.items()
        ],
    }
    validate_online_evidence(evidence, cutoffs, now)
    changed = deepcopy(evidence)
    changed["shops"][1]["videos"] = "2026-10-02"
    with pytest.raises(ValueError, match="跨境7.*cutoff mismatch"):
        validate_online_evidence(changed, cutoffs, now)


def test_source_windows_and_activity_use_each_shops_dates():
    cutoffs = _cutoffs()
    feishu = {
        "source": "feishu-bitable-readonly",
        "tables": [
            {
                "productLine": line,
                "total": 1,
                "rows": [
                    {
                        "accountName": "abc",
                        "bdOwner": "BD",
                        "sampleApprovedDate": "2026-09-01",
                    }
                ],
            }
            for line in ("童车", "遥控车")
        ],
    }
    high_shops = []
    low_shops = []
    for name, dates in cutoffs.items():
        line = "童车" if name in ("跨境3", "跨境7") else "遥控车"
        high = {
            "shopName": name,
            "productLine": line,
            "sourceWindows": {
                "creators": {
                    "from": str(dates["creators"].replace(month=8)),
                    "to": str(dates["creators"]),
                },
                "liveAccounts": {
                    "from": str(dates["liveAccounts"] - relativedelta(months=2)),
                    "to": str(dates["liveAccounts"]),
                },
            },
            "totals": {"creators": 0, "videos": 0, "liveAccounts": 0},
            "creators": [],
            "videos": [],
            "liveAccounts": [],
        }
        low = deepcopy(high)
        low["sourceWindows"]["videos"] = {
            "from": str(dates["videos"].replace(month=dates["videos"].month - 2)),
            "to": str(dates["videos"]),
        }
        high_shops.append(high)
        low_shops.append(low)
    high_shops[1]["creators"] = [{"username": "abc", "affiliateGmvMinor": 1000}]
    high_shops[1]["totals"]["creators"] = 1
    low_shops[1]["videos"] = [
        {"creatorUsername": "abc", "videoPostTime": "2026-10-02T00:00:00-07:00"}
    ]
    low_shops[1]["totals"]["videos"] = 1
    high = {"source": "local-erp-affiliate-center", "shops": high_shops}
    low = {"source": "local-erp-affiliate-center", "shops": low_shops}
    source = validate_sources(feishu, high, low, cutoffs)
    base = {
        ("童车", "abc"): {
            "account": "abc",
            "bd": "BD",
            "sample_day": None,
            "conflict": False,
        }
    }
    desired = desired_rows(
        base, source["high"], source["low"], source["windows"],
        (date(2026, 8, 6), date(2026, 10, 6)),
    )
    assert desired[("童车", "abc")]["业绩"] == 10.0
    assert desired[("童车", "abc")]["视频数"] == 0
    bad = deepcopy(low)
    bad["shops"][1]["sourceWindows"]["videos"]["to"] = "2026-10-02"
    with pytest.raises(ValueError, match="跨境7.videos source window mismatch"):
        validate_sources(feishu, high, bad, cutoffs)
