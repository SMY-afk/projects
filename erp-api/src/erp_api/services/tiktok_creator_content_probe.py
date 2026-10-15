from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRequest,
    TikTokTimeoutError,
    TikTokTransport,
)

CREATOR_INFO_SCOPE = "creator.affiliate.info"
CREATOR_SHOWCASE_SCOPE = "creator.showcase.read"
CREATOR_VIDEO_SCOPE = "creator.video.write"


@dataclass(frozen=True)
class CreatorProbeEndpoint:
    name: str
    path: str
    query: dict[str, str]


READ_ONLY_ENDPOINTS = (
    CreatorProbeEndpoint(
        name="creator_profile",
        path="/affiliate_creator/202508/profiles",
        query={},
    ),
    CreatorProbeEndpoint(
        name="showcase_products",
        path="/affiliate_creator/202405/showcases/products",
        query={"page_size": "1"},
    ),
)


def evaluate_creator_preflight(
    *, user_type: str | int | None, granted_scopes: Iterable[str]
) -> dict[str, object]:
    scopes = sorted({scope.strip() for scope in granted_scopes if scope.strip()})
    is_creator = str(user_type) == "1"
    can_read_profile = bool(
        {CREATOR_INFO_SCOPE, CREATOR_VIDEO_SCOPE}.intersection(scopes)
    )
    can_read_showcase = bool(
        {CREATOR_SHOWCASE_SCOPE, CREATOR_VIDEO_SCOPE}.intersection(scopes)
    )
    can_publish = CREATOR_VIDEO_SCOPE in scopes
    return {
        "userTypeValid": is_creator,
        "grantedScopes": scopes,
        "capabilities": {
            "readProfile": can_read_profile,
            "readShowcase": can_read_showcase,
            "publishVideoOrPhoto": can_publish,
        },
        "readOnlyProbeReady": is_creator and can_read_profile and can_read_showcase,
        "publishProbeReady": is_creator and can_publish,
    }


class TikTokCreatorContentProbe:
    def __init__(self, transport: TikTokTransport) -> None:
        self._transport = transport

    async def run_read_only(self, *, access_token: str) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for endpoint in READ_ONLY_ENDPOINTS:
            results.append(await self._probe(endpoint, access_token=access_token))
        return results

    async def _probe(
        self, endpoint: CreatorProbeEndpoint, *, access_token: str
    ) -> dict[str, object]:
        try:
            response = await self._transport.request_with_metadata(
                TikTokRequest("GET", endpoint.path, query=endpoint.query),
                access_token=access_token,
            )
        except TikTokApiError as error:
            return {
                "endpoint": endpoint.name,
                "status": "rejected",
                "platformCode": error.code,
                "requestId": error.request_id,
                "upstreamStatus": error.upstream_status_code,
            }
        except TikTokTimeoutError:
            return {"endpoint": endpoint.name, "status": "timeout"}
        except TikTokClientError:
            return {"endpoint": endpoint.name, "status": "transport_error"}
        return {
            "endpoint": endpoint.name,
            "status": "success",
            "requestId": response.platform_request_id,
            "upstreamStatus": response.status_code,
            "responseShape": _response_shape(response.payload),
        }


def _response_shape(payload: dict[str, Any]) -> dict[str, object]:
    data = payload.get("data")
    data_keys = sorted(data) if isinstance(data, dict) else []
    list_counts = {
        key: len(value)
        for key, value in (data.items() if isinstance(data, dict) else ())
        if isinstance(value, list)
    }
    return {
        "topLevelKeys": sorted(payload),
        "dataKeys": data_keys,
        "listCounts": list_counts,
    }
