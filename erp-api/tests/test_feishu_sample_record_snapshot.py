from datetime import UTC, datetime

from erp_api.services.feishu_sample_record_snapshot import (
    parse_feishu_record_snapshot,
)


def test_record_snapshot_parses_created_time() -> None:
    snapshot = parse_feishu_record_snapshot(
        {"fields": {}, "created_time": "1789999200000"}
    )

    assert snapshot.created_at == datetime.fromtimestamp(1789999200, tz=UTC)


def test_record_snapshot_parses_creator_metadata() -> None:
    snapshot = parse_feishu_record_snapshot(
        {
            "fields": {},
            "created_by": {"id": "ou-submitter", "name": "Original User"},
        }
    )

    assert snapshot.creator_id == "ou-submitter"
    assert snapshot.creator_name == "Original User"
