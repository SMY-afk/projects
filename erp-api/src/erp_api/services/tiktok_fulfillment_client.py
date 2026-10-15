from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

from erp_api.services.tiktok_transport import TikTokRequest, TikTokTransport


class TikTokFulfillmentClient(Protocol):
    async def ship_package(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        platform_package_id: str,
        tracking_number: str,
        shipping_provider_id: str,
    ) -> str | None: ...


class HttpTikTokFulfillmentClient:
    def __init__(
        self,
        transport: TikTokTransport,
        *,
        ship_path_template: str,
    ) -> None:
        if "{package_id}" not in ship_path_template:
            raise ValueError("TikTok fulfillment path must include {package_id}.")
        self._transport = transport
        self._ship_path_template = ship_path_template

    async def ship_package(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        platform_package_id: str,
        tracking_number: str,
        shipping_provider_id: str,
    ) -> str | None:
        path = self._ship_path_template.format(
            package_id=quote(platform_package_id, safe="")
        )
        response = await self._transport.request_with_metadata(
            TikTokRequest(
                "POST",
                path,
                query={"shop_cipher": shop_cipher},
                json_body={
                    "self_shipment": {
                        "tracking_number": tracking_number,
                        "shipping_provider_id": shipping_provider_id,
                    },
                },
                retryable=False,
            ),
            access_token=access_token,
        )
        return response.platform_request_id
