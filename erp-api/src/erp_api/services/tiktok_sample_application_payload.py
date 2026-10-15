from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from erp_api.services.tiktok_transport import TikTokApiError, TikTokResponse


@dataclass(frozen=True)
class TikTokSampleApplicationPage:
    applications: tuple[dict[str, Any], ...]
    next_page_token: str | None
    total_count: int | None
    platform_request_id: str | None


def _invalid_response() -> TikTokApiError:
    return TikTokApiError(
        "TikTok sample application response is invalid.",
        code="invalid_response",
        status_code=502,
    )


def parse_sample_application_page(
    response: TikTokResponse,
) -> TikTokSampleApplicationPage:
    data = response.payload.get("data")
    if not isinstance(data, dict):
        raise _invalid_response()
    raw_applications = data.get("sample_applications")
    if not isinstance(raw_applications, list):
        raise _invalid_response()
    applications: list[dict[str, Any]] = []
    for application in raw_applications:
        if not isinstance(application, dict):
            raise _invalid_response()
        if not isinstance(application.get("id"), str) or not application["id"]:
            raise _invalid_response()
        if not isinstance(application.get("status"), str) or not application["status"]:
            raise _invalid_response()
        if not isinstance(application.get("creator"), dict):
            raise _invalid_response()
        if not isinstance(application.get("product"), dict):
            raise _invalid_response()
        applications.append(application)

    raw_token = data.get("next_page_token")
    if raw_token in (None, ""):
        next_page_token = None
    elif isinstance(raw_token, str):
        next_page_token = raw_token
    else:
        raise _invalid_response()

    raw_total = data.get("total_count")
    if raw_total is None:
        total_count = None
    elif isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0:
        total_count = raw_total
    else:
        raise _invalid_response()

    if next_page_token and not applications:
        raise TikTokApiError(
            "TikTok sample pagination returned an empty non-terminal page.",
            code="pagination_incomplete",
            status_code=502,
            request_id=response.platform_request_id,
        )
    return TikTokSampleApplicationPage(
        applications=tuple(applications),
        next_page_token=next_page_token,
        total_count=total_count,
        platform_request_id=response.platform_request_id,
    )
