import pytest

from erp_api.services.tiktok_sample_application_payload import (
    parse_sample_application_page,
)
from erp_api.services.tiktok_transport import TikTokApiError, TikTokResponse


def _application(application_id: str = "sample-1") -> dict[str, object]:
    return {
        "id": application_id,
        "status": "PENDING",
        "creator": {},
        "product": {},
    }


def _response(data: object) -> TikTokResponse:
    return TikTokResponse(
        payload={"data": data},
        platform_request_id="request-1",
        status_code=200,
    )


def test_parse_sample_application_page_maps_valid_response() -> None:
    page = parse_sample_application_page(
        _response(
            {
                "sample_applications": [_application()],
                "next_page_token": "next-1",
                "total_count": 2,
            }
        )
    )

    assert len(page.applications) == 1
    assert page.next_page_token == "next-1"
    assert page.total_count == 2
    assert page.platform_request_id == "request-1"


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"sample_applications": {}},
        {"sample_applications": [None]},
        {"sample_applications": [{"id": "sample-1"}]},
        {"sample_applications": [], "next_page_token": 7},
        {"sample_applications": [], "total_count": -1},
    ],
)
def test_parse_sample_application_page_rejects_invalid_shapes(data: object) -> None:
    with pytest.raises(TikTokApiError, match="response is invalid"):
        parse_sample_application_page(_response(data))


def test_parse_sample_application_page_rejects_empty_non_terminal_page() -> None:
    with pytest.raises(TikTokApiError) as captured:
        parse_sample_application_page(
            _response({"sample_applications": [], "next_page_token": "next-1"})
        )

    assert captured.value.code == "pagination_incomplete"
