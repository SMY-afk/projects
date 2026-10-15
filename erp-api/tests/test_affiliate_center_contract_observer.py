import json

import pytest

from erp_api.services.affiliate_center_contract_observer import (
    ContractObservationError,
    observe_response_contract,
)


def test_observer_records_only_safe_contract_metadata() -> None:
    observation = observe_response_contract(
        url=(
            "https://affiliate.example.test/api/creator/list"
            "?sign=dynamic-signature&msToken=browser-token"
        ),
        method="post",
        status=200,
        response_headers={
            "content-type": "application/json; charset=utf-8",
            "x-request-id": "request-header-1",
            "set-cookie": "session=private-cookie",
        },
        payload={
            "data": {
                "items": [
                    {
                        "creator_id": "creator-private-value",
                        "metrics": {"gmv": 1234},
                    }
                ],
                "has_more": False,
                "next_cursor": "private-cursor",
                "total_count": 1,
            },
            "request_id": "request-payload-2",
            "access_token": "private-access-token",
        },
    )

    assert observation == {
        "host": "affiliate.example.test",
        "method": "POST",
        "path": "/api/creator/list",
        "contentType": "application/json; charset=utf-8",
        "status": 200,
        "paginationFields": [
            "data.has_more",
            "data.next_cursor",
            "data.total_count",
        ],
        "responseFieldPaths": [
            "access_token",
            "data",
            "data.has_more",
            "data.items",
            "data.items[]",
            "data.items[].creator_id",
            "data.items[].metrics",
            "data.items[].metrics.gmv",
            "data.next_cursor",
            "data.total_count",
            "request_id",
        ],
        "requestIds": [
            {"source": "header.x-request-id", "value": "request-header-1"},
            {"source": "payload.request_id", "value": "request-payload-2"},
        ],
    }
    encoded = json.dumps(observation)
    for forbidden_value in (
        "dynamic-signature",
        "browser-token",
        "private-cookie",
        "creator-private-value",
        "private-cursor",
        "private-access-token",
    ):
        assert forbidden_value not in encoded
    assert "?" not in observation["path"]


def test_observer_ignores_unapproved_request_id_headers_and_values() -> None:
    observation = observe_response_contract(
        url="https://affiliate.example.test/api/videos",
        method="GET",
        status=204,
        response_headers={
            "content-type": "application/json",
            "authorization": "secret",
            "x-request-id": "contains whitespace and is rejected",
        },
        payload={"data": []},
    )

    assert observation["requestIds"] == []


def test_observer_recognizes_observed_tiktok_pagination_names() -> None:
    observation = observe_response_contract(
        url="https://affiliate.example.test/api/creators",
        method="POST",
        status=200,
        response_headers={"content-type": "application/json"},
        payload={
            "data": {
                "next_pagination": {
                    "has_more": True,
                    "next_page": 2,
                    "total": 572,
                    "total_page": 58,
                }
            }
        },
    )

    assert observation["paginationFields"] == [
        "data.next_pagination.has_more",
        "data.next_pagination.next_page",
        "data.next_pagination.total",
        "data.next_pagination.total_page",
    ]


def test_observer_requires_matching_discriminator_when_resource_is_given() -> None:
    with pytest.raises(ContractObservationError):
        observe_response_contract(
            resource="creators",
            url="https://affiliate.example.test/api/creators",
            method="POST",
            status=200,
            response_headers={"content-type": "application/json"},
            payload={"code": 0, "data": {"video_list_segments_v2": []}},
        )
