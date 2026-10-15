"""Nightly plans must leave the default seven-day pages readable."""

import builtins
import runpy
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts import plan_daily_affiliate_exports as planner

CREATOR_CUTOFF = date(2026, 10, 13)
VIDEO_CUTOFF = date(2026, 10, 11)


def test_planner_loads_without_api_only_creator_window_service(monkeypatch):
    original_import = builtins.__import__

    def worker_import(name, *args, **kwargs):
        if name == "erp_api.services.affiliate_creator_window_coverage":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", worker_import)
    runpy.run_path(planner.__file__)


def video_run(name, start, end, *, complete=True):
    return {
        "shop": name, "resource": "video", "status": "succeeded",
        "window": (start, end), "fetched": 10,
        "persisted": 10 if complete else 9,
    }


@pytest.fixture
def build_plan(monkeypatch):
    tenant_id = UUID(int=1)
    shops = [
        SimpleNamespace(
            tenant_id=tenant_id, shop_id=UUID(int=index + 2),
            source_name=target.source_name, timezone="America/Los_Angeles",
            currency="USD",
        )
        for index, target in enumerate(planner.TARGET_SHOPS)
    ]

    class Health:
        def __init__(self, _redis):
            pass

        async def get(self, *_args):
            return SimpleNamespace(state="online", session_available=True)

        async def observed_evidence_for(self, *_args, **_kwargs):
            cutoff = CREATOR_CUTOFF if _args[-1] == "creators" else VIDEO_CUTOFF
            return cutoff, datetime.now(UTC)

    async def active_shops(_database):
        return shops

    async def released(*_args, **_kwargs):
        return True

    monkeypatch.setattr(planner, "get_settings", lambda: SimpleNamespace(
        affiliate_export_tenant_id=tenant_id,
    ))
    monkeypatch.setattr(planner, "_active_live_shops", active_shops)
    monkeypatch.setattr(planner, "AffiliateCaptureHealthRepository", Health)
    monkeypatch.setattr(planner, "sample_round_releases_affiliate", released)

    async def run(*, creator_recent=(), video_recent=(), rolling=True):
        async def reports(*_args):
            prior = planner.rolling_windows(CREATOR_CUTOFF) if rolling else []
            return set(prior) | set(creator_recent)

        async def runs(_database, _shop, name):
            windows = planner.rolling_windows(VIDEO_CUTOFF) if rolling else []
            return [video_run(name, first, last) for first, last in windows] + [
                video_run(name, *window) for window in video_recent
            ]

        monkeypatch.setattr(planner, "creator_report_windows", reports)
        monkeypatch.setattr(planner, "successful_runs", runs)
        return await planner.build_plan(None, None, datetime.now(UTC))

    return run


@pytest.mark.asyncio
async def test_complete_rolling_reports_still_require_default_seven_days(build_plan):
    plan = await build_plan()
    expected = [
        {"resource": "creators", "start": "2026-10-07", "end": "2026-10-13"},
        {"resource": "videos", "start": "2026-10-05", "end": "2026-10-09"},
    ]
    assert len(plan["shops"]) == 5
    for shop in plan["shops"]:
        assert shop["missing"] == expected


@pytest.mark.asyncio
async def test_recent_complete_component_reports_are_reused(build_plan):
    plan = await build_plan(
        creator_recent=[
            (date(2026, 10, 7), date(2026, 10, 10)),
            (date(2026, 10, 11), CREATOR_CUTOFF),
        ],
        video_recent=[(date(2026, 10, 5), date(2026, 10, 9))],
    )
    assert all(shop["missing"] == [] for shop in plan["shops"])


@pytest.mark.asyncio
async def test_creator_reuses_viable_path_after_longer_dead_end(build_plan):
    plan = await build_plan(creator_recent=[
        (date(2026, 10, 7), date(2026, 10, 10)),
        (date(2026, 10, 7), date(2026, 10, 9)),
        (date(2026, 10, 10), date(2026, 10, 11)),
    ])
    assert all(not any(item["resource"] == "creators" for item in shop["missing"])
               for shop in plan["shops"])


@pytest.mark.asyncio
async def test_recent_creator_overlap_does_not_count_as_exact_coverage(build_plan):
    plan = await build_plan(creator_recent=[
        (date(2026, 10, 7), date(2026, 10, 10)),
        (date(2026, 10, 10), CREATOR_CUTOFF),
    ])
    assert all(
        {"resource": "creators", "start": "2026-10-07", "end": "2026-10-13"}
        in shop["missing"] for shop in plan["shops"]
    )


def test_recent_video_path_captures_only_uncovered_tail():
    first, last = date(2026, 10, 5), VIDEO_CUTOFF
    runs = [
        video_run("跨境3", first, last - timedelta(days=1)),
        video_run("跨境3", last, last, complete=False),
        video_run("跨境4", last, last),
    ]
    assert planner.exact_video_path_missing("跨境3", last, runs, start=first) == [
        {"resource": "videos", "start": "2026-10-11", "end": "2026-10-11"},
    ]


@pytest.mark.asyncio
async def test_rolling_gaps_remain_and_duplicate_repairs_are_removed(build_plan):
    plan = await build_plan(rolling=False)
    for shop in plan["shops"]:
        keys = [(item["resource"], item["start"], item["end"])
                for item in shop["missing"]]
        assert len(keys) == len(set(keys))
        for resource, cutoff in [("creators", CREATOR_CUTOFF), ("videos", VIDEO_CUTOFF)]:
            assert all((resource, str(first), str(last)) in keys
                       for first, last in planner.rolling_windows(cutoff))
