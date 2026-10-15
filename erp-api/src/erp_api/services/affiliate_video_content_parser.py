from __future__ import annotations

from collections.abc import Mapping

from erp_api.services.affiliate_center_metric_dtos import AffiliateVideoProductDTO
from erp_api.services.affiliate_metric_parse_support import image_url, text
from erp_api.services.affiliate_metric_source_contract import extensions

_PAGE_PRODUCT_FIELDS = frozenset({"id", "title", "cover"})
_CANONICAL_PRODUCT_FIELDS = frozenset(
    {"productId", "title", "coverImageUrl", "id", "name"}
)


def first_play_url(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    return text(value[0], "playUrl")


def parse_page_products(value: object) -> tuple[AffiliateVideoProductDTO, ...]:
    if not isinstance(value, list):
        raise TypeError("product_base_list: expected a list")
    return tuple(_page_product(item) for item in value)


def parse_canonical_products(value: object) -> tuple[AffiliateVideoProductDTO, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("promotedProducts: expected a list")
    return tuple(_canonical_product(item) for item in value)


def _page_product(value: object) -> AffiliateVideoProductDTO:
    if not isinstance(value, Mapping):
        raise TypeError("product_base_list item: expected an object")
    return AffiliateVideoProductDTO(
        product_id=text(value.get("id"), "productId", required=True) or "",
        title=text(value.get("title"), "productTitle"),
        cover_image_url=image_url(value.get("cover"), "productCoverImageUrl"),
        extensions=extensions(value, _PAGE_PRODUCT_FIELDS),
    )


def _canonical_product(value: object) -> AffiliateVideoProductDTO:
    if not isinstance(value, Mapping):
        raise TypeError("promotedProducts item: expected an object")
    return AffiliateVideoProductDTO(
        product_id=text(
            value.get("productId", value.get("id")),
            "productId",
            required=True,
        )
        or "",
        title=text(value.get("title", value.get("name")), "productTitle"),
        cover_image_url=image_url(value.get("coverImageUrl"), "productCoverImageUrl"),
        extensions=extensions(value, _CANONICAL_PRODUCT_FIELDS),
    )
