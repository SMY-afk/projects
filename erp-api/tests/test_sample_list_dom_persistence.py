from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services.tiktok_sample_list_dom import (
    SampleListDomScore,
    sample_score_persistence_item,
)
from erp_api.services.affiliate_creator_summary_repository import _updated_extensions
from erp_api.services.sample_notification_profile_builder import (
    creator_details_snapshot,
)


def test_standalone_dom_score_stays_incomplete_with_explicit_provenance() -> None:
    observed_at = datetime(2026, 9, 11, 4, tzinfo=UTC)
    item = sample_score_persistence_item(
        platform_creator_id="page-creator-1",
        creator_username="creator_one",
        score=SampleListDomScore("86", "86", observed_at),
    )

    summary, request_id, response_path = item
    extensions = _updated_extensions(
        {},
        summary,
        shop_id=uuid4(),
        open_id="open-1",
        username="creator_one",
        request_id=request_id,
        response_path=response_path,
    )
    details = extensions["creator_details_summary"]
    snapshot = creator_details_snapshot(SimpleNamespace(extensions=extensions))

    assert set(details["sources"]) == {"sample_list_dom"}
    assert details["source_payloads"]["sample_list_dom"] == {
        "source": "sample_request_table_dom",
        "header": "Sample score",
        "display_value": "86",
    }
    assert snapshot["sample_score"]["overall"] == "86"
    assert "creator_details_complete" not in snapshot
