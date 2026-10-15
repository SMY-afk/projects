import inspect
from datetime import date
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from backend.app.services.tiktok_affiliate_creator_detail_backfill import (
    TikTokAffiliateCreatorDetailBackfill,
    _detail_url,
)
from backend.app.services.tiktok_affiliate_creator_detail_backfill_factory import (
    _creator_usernames,
)
from backend.app.services.tiktok_affiliate_creator_identity_collector import (
    CreatorDetailBackfillError,
    page_platform_shop_id,
    pagination,
)
from backend.app.services.tiktok_affiliate_creator_identity_sample import (
    _batch_request_body,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_creator_detail_backfill_repository import (
    CreatorDetailBackfillTarget,
)


def _target() -> CreatorDetailBackfillTarget:
    return CreatorDetailBackfillTarget(
        query=AffiliateCenterQuery(
            resource=AffiliateCenterResource.CREATORS,
            shop_id=uuid4(),
            window_start=date(2026, 8, 19),
            window_end=date(2026, 8, 25),
            shop_timezone="America/Los_Angeles",
            currency="USD",
            filters={},
        ),
        platform_shop_id="9768147009521852682",
    )


def test_detail_url_contains_only_approved_navigation_dimensions() -> None:
    split = urlsplit(_detail_url(_target(), "US", "9677336294324206133"))

    assert split.scheme == "https"
    assert split.hostname == "affiliate.tiktokshopglobalselling.com"
    assert split.path == "/data/creator-analysis"
    assert parse_qs(split.query) == {
        "creator_id": ["9677336294324206133"],
        "shop_region": ["US"],
        "shop_id": ["9768147009521852682"],
    }


def test_creator_pagination_requires_confirmed_shape() -> None:
    payload = {
        "data": {
            "segments": [
                {"list_control": {"next_pagination": {"has_more": True, "total": 561}}}
            ]
        }
    }

    assert pagination(payload) == (True, 561)

    with pytest.raises(CreatorDetailBackfillError):
        pagination({"data": {"segments": []}})


def test_avatar_batch_request_uses_large_zero_based_pages() -> None:
    original = {
        "request": {
            "requests": [{"list_control": {"pagination": {"size": 50, "page": 0}}}]
        }
    }

    result = _batch_request_body(original, 4)

    assert result["request"]["requests"][0]["list_control"]["pagination"] == {
        "size": 200,
        "page": 4,
    }
    assert original["request"]["requests"][0]["list_control"]["pagination"] == {
        "size": 50,
        "page": 0,
    }


def test_list_page_shop_id_uses_page_navigation_dimension() -> None:
    url = (
        "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
        "?shop_region=US&shop_id=9768147009521852682"
    )

    assert page_platform_shop_id(url) == "9768147009521852682"


def test_detail_backfill_reuses_the_creator_list_page_without_tab_fanout() -> None:
    source = inspect.getsource(TikTokAffiliateCreatorDetailBackfill._crawl_details)

    assert "new_page" not in source
    assert "detail_page = list_page" in source
    assert "await detail_page.goto(list_url" in source
    assert "concurrency=1" in source


def test_detail_backfill_test_whitelist_is_normalized(monkeypatch) -> None:
    monkeypatch.setenv(
        "AFFILIATE_DETAIL_CREATOR_USERNAMES", "@LetsBeHayleyWhite, SECOND "
    )

    assert _creator_usernames() == frozenset({"letsbehayleywhite", "second"})
