"""Use short official-local idle windows while preserving free-sample priority."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import sample_capture_priority as priority


@pytest.mark.parametrize('remaining,expected',[(100,70),(89,0),(180,90)])
def test_verified_official_local_window_keeps_thirty_second_margin(tmp_path,remaining,expected):
    priority.finish_free('local',True,datetime.now(UTC)+timedelta(seconds=remaining),root=tmp_path)
    path=tmp_path/'local.free-priority.json'
    row=json.loads(path.read_text())
    row['source_policy_result']='official_api_available'
    path.write_text(json.dumps(row))
    before=path.read_bytes()
    assert priority.secondary_budget('local',root=tmp_path)==pytest.approx(expected,abs=0.2)
    assert path.read_bytes()==before


def test_short_local_window_requires_verified_official_source(tmp_path):
    priority.finish_free('local',True,datetime.now(UTC)+timedelta(seconds=100),root=tmp_path)
    assert priority.secondary_budget('local',root=tmp_path)==0


def test_requested_free_round_still_preempts_short_local_window(tmp_path):
    priority.finish_free('local',True,datetime.now(UTC)+timedelta(seconds=100),root=tmp_path)
    path=tmp_path/'local.free-priority.json'
    row=json.loads(path.read_text())
    row['source_policy_result']='official_api_available'
    row['state']='requested'
    path.write_text(json.dumps(row))
    assert priority.secondary_budget('local',root=tmp_path)==0
