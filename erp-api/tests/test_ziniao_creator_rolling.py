from datetime import date
from pathlib import Path

from scripts.run_ziniao_creator_rolling import rolling_windows


def test_rolling_windows_follow_the_latest_tiktok_day() -> None:
    assert rolling_windows(date(2026, 8, 31)) == [
        (date(2026, 8, 31), date(2026, 8, 31), "today"),
        (date(2026, 8, 25), date(2026, 8, 31), "last7d"),
        (date(2026, 7, 3), date(2026, 8, 1), "days31to60"),
        (date(2026, 8, 2), date(2026, 8, 31), "last30d"),
    ]


def test_ziniao_entrypoints_disable_degraded_wmi_before_sqlalchemy_imports() -> None:
    project_root = Path(__file__).parents[1]
    for relative_path in (
        "scripts/run_ziniao_creator_rolling.py",
        "scripts/run_ziniao_affiliate_watch.py",
    ):
        source = (project_root / relative_path).read_text(encoding="utf-8")
        assert source.index("platform._wmi = None") < source.index("from sqlalchemy")
