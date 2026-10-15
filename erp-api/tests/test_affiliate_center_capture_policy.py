import pytest

from erp_api.services.affiliate_center_capture_policy import (
    AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS,
    CAPTURE_EXECUTION_BOUNDARY,
    CapturePolicyError,
    affiliate_center_capture_policy_contract,
    evaluate_capture_completeness,
    sanitize_capture_payload,
    validate_capture_log_fields,
)
from erp_api.services.affiliate_center_display_contract import (
    affiliate_center_display_contract,
)


def test_capture_stays_in_current_browser_session_with_seven_day_raw_ttl() -> None:
    assert CAPTURE_EXECUTION_BOUNDARY == "current_browser_session_only"
    assert AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS == 7


def test_trigger_ownership_separates_listener_from_arq() -> None:
    ownership = affiliate_center_capture_policy_contract()["triggerOwnership"]

    assert ownership == {
        "pageCapture": {
            "owner": "capture_daemon",
            "trigger": "queued_sync_intent",
            "apiOrArqCanForce": False,
        },
        "officialApi": {
            "owner": "arq",
            "triggers": ["scheduled", "manual"],
        },
    }


def test_raw_payload_sanitizer_removes_credentials_pii_and_messages() -> None:
    sanitized = sanitize_capture_payload(
        {
            "data": {
                "items": [
                    {
                        "id": "creator-1",
                        "username": "creator",
                        "metrics": {"gmv": "12.34"},
                        "email": "private@example.test",
                        "message": "private chat",
                    }
                ]
            },
            "access_token": "secret",
            "token": "generic-secret",
            "msToken": "browser-secret",
            "shop_cipher": "shop-secret",
            "sign": "signature-secret",
            "query_string": "shop_cipher=shop-secret",
            "headers": {"Cookie": "session=secret"},
        }
    )

    assert sanitized == {
        "data": {
            "items": [
                {
                    "id": "creator-1",
                    "username": "creator",
                    "metrics": {"gmv": "12.34"},
                }
            ]
        }
    }


def test_raw_payload_sanitizer_strips_url_query_credentials() -> None:
    source_url = (
        "https://p16-common-sign.tiktokcdn-us.com/avatar.jpeg"
        "?refresh_token=private&x-signature=private#fragment"
    )

    sanitized = sanitize_capture_payload(
        {"creator": {"avatar_url": source_url, "profile_url": source_url}}
    )

    assert sanitized == {
        "creator": {
            "avatar_url": "https://p16-common-sign.tiktokcdn-us.com/avatar.jpeg",
            "profile_url": "https://p16-common-sign.tiktokcdn-us.com/avatar.jpeg",
        }
    }


def test_capture_logs_are_strictly_allowlisted() -> None:
    assert (
        validate_capture_log_fields(
            {
                "event": "affiliate_capture_page",
                "tenant_id": "tenant-1",
                "shop_id": "shop-1",
                "run_id": "run-1",
                "request_id": "request-1",
                "records_unique": 50,
            }
        )["records_unique"]
        == 50
    )

    for forbidden in (
        "payload",
        "cursor",
        "url",
        "authorization",
        "host",
        "path",
        "status",
        "failure_category",
        "cdp_host",
        "cdp_port",
        "error_type",
    ):
        with pytest.raises(CapturePolicyError, match="allowlist"):
            validate_capture_log_fields({forbidden: "secret"})


@pytest.mark.parametrize(
    ("has_more", "next_cursor", "unique_count", "total_count", "complete", "reason"),
    [
        (False, "cursor-from-last-page", 100, 100, True, "complete"),
        (True, "", 100, 100, False, "cursor_interrupted"),
        (True, "next", 50, 100, False, "pagination_not_terminal"),
        (False, None, 99, 100, False, "total_count_mismatch"),
        (False, None, 99, None, True, "complete"),
    ],
)
def test_full_capture_requires_terminal_pagination_and_matching_unique_total(
    has_more, next_cursor, unique_count, total_count, complete, reason
) -> None:
    result = evaluate_capture_completeness(
        has_more=has_more,
        next_cursor=next_cursor,
        unique_record_count=unique_count,
        total_count=total_count,
    )

    assert result.complete is complete
    assert result.reason == reason


def test_display_contract_freezes_creator_metrics_and_sorting() -> None:
    contract = affiliate_center_display_contract()
    creators = contract["creators"]
    videos = contract["videos"]

    assert creators["currencySource"] == "query.currency"
    assert creators["windowSemantics"] == "inclusive_shop_local_dates"
    assert creators["defaultSort"] == [
        {"field": "affiliateGmvMinor", "direction": "desc"},
        {"field": "username", "direction": "asc"},
    ]
    assert {item["field"] for item in creators["metrics"]} == {
        "username",
        "affiliateGmvMinor",
        "affiliateVideoGmvMinor",
        "affiliateLiveGmvMinor",
        "estimatedCommissionMinor",
        "affiliateOrderCount",
        "itemsSold",
        "productImpressions",
        "clickThroughRate",
        "affiliateVideoCount",
        "affiliateLiveCount",
        "affiliateFollowerCount",
    }
    assert videos["status"] == "awaiting_verified_payload"
    assert videos["metrics"] == []
