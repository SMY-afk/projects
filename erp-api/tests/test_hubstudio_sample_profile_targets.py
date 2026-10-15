from datetime import UTC, datetime, timedelta
from uuid import uuid4

from erp_api.services.hubstudio_sample_profile_targets import (
    _matching_profile_rows,
    _targets,
)

NOW = datetime(2026, 9, 11, 10, 30, tzinfo=UTC)
COMPLETE = {"schema_version": 2, "creator_details_complete": True}


def test_targets_only_include_missing_or_daily_stale_details() -> None:
    fresh = uuid4()
    missing_one = uuid4()
    missing_two = uuid4()
    recent = uuid4()
    daily_stale = uuid4()
    rows = [
        (fresh, "@FreshCreator", 100_000, "L1", COMPLETE, NOW - timedelta(minutes=1)),
        (missing_one, "NeedsDetails", None, None, None, None),
        (missing_two, "needsdetails", None, None, {}, None),
        (recent, "RecentCreator", 100_000, "L1", COMPLETE, NOW - timedelta(hours=2)),
        (
            daily_stale,
            "DailyStaleCreator",
            100_000,
            "L1",
            COMPLETE,
            NOW - timedelta(hours=24, seconds=1),
        ),
        (uuid4(), None, None, None, None, None),
    ]

    targets = _targets(rows, now=NOW)

    assert [target.username for target in targets] == [
        "needsdetails",
        "dailystalecreator",
    ]
    assert targets[0].outbox_ids == frozenset({missing_one, missing_two})
    assert targets[1].outbox_ids == frozenset({daily_stale})


def test_targets_back_off_recent_incomplete_profile_attempt() -> None:
    target_id = uuid4()

    targets = _targets(
        [(target_id, "MissingGmv", None, None, COMPLETE, NOW)],
        now=NOW,
    )

    assert targets == []


def test_targets_retry_incomplete_profile_after_one_hour() -> None:
    target_id = uuid4()

    targets = _targets(
        [
            (
                target_id,
                "MissingGmv",
                None,
                None,
                {},
                NOW - timedelta(hours=1, seconds=1),
            )
        ],
        now=NOW,
    )

    assert [target.username for target in targets] == ["missinggmv"]
    assert targets[0].outbox_ids == frozenset({target_id})


def test_targets_use_complete_affiliate_details_as_freshness_evidence() -> None:
    details = {
        "creator_details_summary": {
            "profile_snapshot": {"schema_version": 2},
            "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
            "sources": {
                "profile": {},
                "performance": {},
                "followers": {},
                "trends": {},
                "examples": {},
            },
        }
    }

    targets = _targets(
        [(uuid4(), "AlreadyCaptured", 100_000, "L1", None, None, details)],
        now=NOW,
    )

    assert targets == []


def test_grouped_applications_match_real_tiktok_source_ids() -> None:
    single_outbox = uuid4()
    multiple_outbox = uuid4()
    rows = [
        (
            single_outbox,
            "creator-group:single",
            {"source_item_ids": ["single-application"]},
            "SingleCreator",
            None,
            None,
            None,
            None,
            {},
        ),
        (
            multiple_outbox,
            "creator-group:multiple",
            {"source_item_ids": ["first-product", "second-product"]},
            "MultipleCreator",
            None,
            None,
            None,
            None,
            {},
        ),
        (
            uuid4(),
            "creator-group:unrelated",
            {"source_item_ids": ["unrelated-product"]},
            "UnrelatedCreator",
            None,
            None,
            None,
            None,
            {},
        ),
    ]

    matches = _matching_profile_rows(
        rows,
        {"single-application", "second-product"},
    )

    assert [row[1] for row in matches] == ["SingleCreator", "MultipleCreator"]
    assert [row[0] for row in matches] == [single_outbox, multiple_outbox]
