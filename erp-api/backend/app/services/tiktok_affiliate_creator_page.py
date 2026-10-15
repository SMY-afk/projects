from collections.abc import Mapping

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_creator_payload import (
    creator_pagination_mode,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliateSourcePageContext,
)
from erp_api.services.affiliate_center_source_adapters import map_page_capture


def map_creator_page(
    query: AffiliateCenterQuery,
    payload: Mapping[str, object],
    observation: Mapping[str, object],
    response_context: AffiliateAnalyticsResponseContext,
    page_number: int,
    next_page_number: int | None,
) -> AffiliateCenterPageDTO:
    if not response_context.request_id:
        raise ValueError("Affiliate creator response request ID is required.")
    context = AffiliateSourcePageContext(
        request_id=response_context.request_id,
        pagination_mode=creator_pagination_mode(observation),
        page_number=page_number,
        next_cursor=(f"page:{next_page_number}" if next_page_number else None),
        has_more=next_page_number is not None,
    )
    return map_page_capture(query, payload, context=context)
