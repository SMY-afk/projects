from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from erp_api.services.sample_application_upsert import (
    CREATOR_PROFILE_BUNDLE_FIELDS,
    changed_sample_fields,
)


@pytest.mark.parametrize("sample_type,complete,accepted", [
    ("refundable", True, True), ("refundable", False, False),
    ("free", True, False),
])
def test_verified_paid_profile_is_not_discarded_by_the_free_performance_guard(
    sample_type, complete, accepted
):
    existing = SimpleNamespace(raw_payload={}, creator_profile_snapshot=None)
    normalized = {
        "sample_type": sample_type, "source_type": "hubstudio_cdp",
        "creator_profile_snapshot": {"creator_details_complete": complete},
        "creator_profile_source_type": "hubstudio_cdp",
        "creator_profile_observed_at": datetime.now(UTC),
        "raw_payload": {},
    }
    changed = changed_sample_fields(existing, normalized, performance_fields=frozenset())
    assert CREATOR_PROFILE_BUNDLE_FIELDS.issubset(changed) is accepted
