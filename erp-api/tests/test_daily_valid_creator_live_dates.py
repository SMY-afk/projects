from datetime import UTC, date, datetime

import pytest
from dateutil.relativedelta import relativedelta

from erp_api.services.affiliate_local_export_window import resolve_export_windows
from scripts.daily_valid_creator_batch import expected_windows
from scripts.daily_valid_creator_core import SHOP_LINES, desired_rows, validate_sources
from scripts.daily_valid_creator_dates import parse_shop_cutoffs
from scripts.daily_valid_creator_online import validate_online_evidence


def _cutoffs():
    return parse_shop_cutoffs(
        [
            f"{name},2026-10-04,2026-10-02,2026-10-03"
            for name in ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
        ],
        today=date(2026, 10, 6),
    )


def test_live_cutoff_is_required_and_independent():
    cutoffs = _cutoffs()
    assert cutoffs["跨境3"] == {
        "creators": date(2026, 10, 4),
        "videos": date(2026, 10, 2),
        "liveAccounts": date(2026, 10, 3),
    }
    with pytest.raises(ValueError, match="LIVE_END"):
        parse_shop_cutoffs(["跨境3,2026-10-04,2026-10-02"] * 5)


def test_live_batch_windows_use_live_date_not_creator_date():
    windows = expected_windows(_cutoffs())
    assert ("跨境3", "live", date(2026, 10, 2), date(2026, 10, 3)) in windows
    assert ("跨境3", "live", date(2026, 10, 3), date(2026, 10, 4)) not in windows


def test_online_evidence_requires_separate_live_api_date():
    cutoffs = _cutoffs()
    now = datetime(2026, 10, 6, 3, tzinfo=UTC)
    evidence = {
        "source": "direct_tk_sources",
        "shops": [
            {
                "shop": name,
                "observed_at": now.isoformat(),
                "creators": "2026-10-04",
                "videos": "2026-10-02",
                "liveAccounts": "2026-10-03",
            }
            for name in cutoffs
        ],
    }
    validate_online_evidence(evidence, cutoffs, now)
    evidence["shops"][0]["liveAccounts"] = "2026-10-04"
    with pytest.raises(ValueError, match="liveAccounts"):
        validate_online_evidence(evidence, cutoffs, now)


def test_export_windows_shift_live_independently():
    windows = resolve_export_windows(
        date(2026, 8, 4),
        date(2026, 10, 4),
        {
            "creators": date(2026, 10, 4),
            "videos": date(2026, 10, 2),
            "liveAccounts": date(2026, 10, 3),
        },
    )
    assert windows.creators == (date(2026, 8, 4), date(2026, 10, 4))
    assert windows.videos == (date(2026, 8, 2), date(2026, 10, 2))
    assert windows.live_accounts == (date(2026, 8, 3), date(2026, 10, 3))


def test_two_month_live_window_stays_two_calendar_months_at_month_edge():
    windows = resolve_export_windows(
        date(2026, 1, 30),
        date(2026, 3, 30),
        {
            "creators": date(2026, 3, 30),
            "videos": date(2026, 3, 29),
            "liveAccounts": date(2026, 2, 28),
        },
    )
    assert windows.live_accounts == (date(2025, 12, 28), date(2026, 2, 28))


def test_source_and_live_activity_follow_live_window_only():
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
    shops = []
    for name, line in SHOP_LINES.items():
        windows = {
            resource: {
                "from": str(end - relativedelta(months=2)),
                "to": str(end),
            }
            for resource, end in cutoffs[name].items()
        }
        shops.append(
            {
                "shopName": name,
                "productLine": line,
                "sourceWindows": windows,
                "totals": {"creators": 0, "videos": 0, "liveAccounts": 0},
                "creators": [],
                "videos": [],
                "liveAccounts": [],
            }
        )
    shops[0]["liveAccounts"] = [
        {"fields": {"username": "abc", "startTime": "2026-10-03T12:00:00-07:00"}},
        {"fields": {"username": "abc", "startTime": "2026-10-04T12:00:00-07:00"}},
    ]
    shops[0]["totals"]["liveAccounts"] = 2
    payload = {"source": "local-erp-affiliate-center", "shops": shops}
    source = validate_sources(feishu, payload, payload, cutoffs)
    base = {
        ("童车", "abc"): {
            "account": "abc",
            "bd": "BD",
            "sample_day": None,
            "conflict": False,
        }
    }
    result = desired_rows(
        base, source["high"], source["low"], source["windows"],
        (date(2026, 8, 6), date(2026, 10, 6)),
    )
    assert result[("童车", "abc")]["直播数"] == 1
    shops[0]["sourceWindows"]["liveAccounts"]["to"] = "2026-10-04"
    with pytest.raises(ValueError, match="liveAccounts source window mismatch"):
        validate_sources(feishu, payload, payload, cutoffs)
