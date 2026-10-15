import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from scripts import run_local_affiliate_dates as dates


def test_sample_capture_has_priority_over_direct_date_probe(tmp_path: Path) -> None:
    status_dir = tmp_path / "samples"
    status_dir.mkdir()
    path = status_dir / "cross-border-3.status.json"
    path.write_text(
        json.dumps({"state": "capturing", "at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    assert dates.sample_idle_status(status_dir, "cross-border-3") is None
    path.write_text(
        json.dumps({"state": "stored", "at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    assert dates.sample_idle_status(status_dir, "cross-border-3") is not None


def test_matching_stored_cycle_remains_valid_after_probe_window(tmp_path: Path) -> None:
    status_dir = tmp_path / "samples"
    status_dir.mkdir()
    at = (datetime.now(UTC) - timedelta(seconds=70)).isoformat()
    (status_dir / "cross-border-3.status.json").write_text(
        json.dumps({"state": "stored", "at": at}), encoding="utf-8"
    )
    assert dates.sample_idle_status(status_dir, "cross-border-3") is None
    assert dates.sample_idle_status(status_dir, "cross-border-3", require_recent=False) == at


def test_date_sender_preserves_direct_observation_time() -> None:
    observed_at = "2026-10-09T11:00:00+00:00"
    payloads = []

    class Client:
        async def post(self, _url, **kwargs):
            payloads.append(kwargs["json"])
            return SimpleNamespace(status_code=202, json=lambda: {"status": "stored"})

    args = SimpleNamespace(api_url="https://example.com/health")
    asyncio.run(
        dates.send_dates(
            Client(),
            args,
            "x" * 40,
            "cross-border-3",
            {
                "shop": "跨境3",
                "observed_at": observed_at,
                "creators": "2026-10-07",
                "videos": "2026-10-06",
            },
        )
    )
    assert {item["observed_at"] for item in payloads[0]["dates"]} == {observed_at}
    assert payloads[0]["observed_at"] != observed_at
