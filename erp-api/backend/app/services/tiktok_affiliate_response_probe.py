from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from playwright.async_api import Page, Response

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    RESOURCE_ENDPOINT,
)
from backend.app.services.tiktok_affiliate_intent_types import IntentPageError
from erp_api.services.affiliate_center_payload_contract import (
    AffiliatePayloadDiscriminatorError,
    require_affiliate_payload,
)

RESPONSE_TIMEOUT_MS = 30_000


async def probe_affiliate_page(page: Page, resource: str) -> Response:
    endpoint = RESOURCE_ENDPOINT[resource]
    responses: asyncio.Queue[Response] = asyncio.Queue()
    incompatible_payload_seen = False

    def observe(response: Response) -> None:
        if (
            urlsplit(response.url).path == endpoint
            and response.request.method.upper() == "POST"
        ):
            responses.put_nowait(response)

    page.on("response", observe)
    try:
        async with asyncio.timeout(RESPONSE_TIMEOUT_MS / 1000):
            await trigger_probe_request(page, resource)
            while True:
                response = await responses.get()
                if response.status != 200:
                    return response
                try:
                    require_affiliate_payload(resource, await response.json())
                except (AffiliatePayloadDiscriminatorError, ValueError, TypeError):
                    incompatible_payload_seen = True
                    continue
                return response
    except TimeoutError as error:
        category = (
            "payload_structure_changed"
            if incompatible_payload_seen
            else "request_timeout"
        )
        raise IntentPageError(category) from error
    except IntentPageError:
        raise
    except Exception as error:
        raise IntentPageError("request_timeout") from error
    finally:
        page.remove_listener("response", observe)


async def trigger_probe_request(page: Page, resource: str) -> None:
    await page.reload(wait_until="domcontentloaded")
