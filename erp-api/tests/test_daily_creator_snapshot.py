import json

from scripts.daily_valid_creator_snapshot import save_snapshot


def test_snapshot_persists_before_and_plan_without_overwrite(tmp_path):
    before = [{"record_id": "old", "fields": {"账号名称": "creator"}}]
    plan = {"hash": "hash", "operations": {"update": [], "create": [], "delete": []}}
    first = save_snapshot(tmp_path, before, plan)
    second = save_snapshot(tmp_path, before, plan)
    assert first != second
    data = json.loads(first.read_text(encoding="utf-8"))
    assert data["baseline"] == before
    assert data["plan"] == plan
