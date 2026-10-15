from datetime import date

import pytest

from scripts import probe_daily_valid_creator_online as probe


@pytest.mark.asyncio
async def test_probe_retries_only_missing_resource(monkeypatch) -> None:
    calls = []

    async def detect(_contexts, resources):
        resource = resources[0]
        calls.append(resource)
        if resource == "videos" and calls.count("videos") == 1:
            return {}
        return {resource: date(2026, 10, 4 if resource == "creators" else 3)}

    monkeypatch.setattr(probe, "detect_latest_selectable_dates", detect)
    result = await probe.detect_required_dates([object()])
    assert result == {"creators": date(2026, 10, 4), "videos": date(2026, 10, 3)}
    assert calls == ["creators", "videos", "videos"]
