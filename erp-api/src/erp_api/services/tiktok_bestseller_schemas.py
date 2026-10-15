from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal

from erp_api.services.tiktok_transport import TikTokApiError

BestsellerEntityType = Literal["product", "creator", "video", "live"]
BestsellerCurrency = Literal["USD", "LOCAL"]


@dataclass(frozen=True)
class DesensitizedGmvRange:
    raw: str
    currency_context: BestsellerCurrency
    computable: Literal[False] = False


@dataclass(frozen=True)
class TikTokBestsellerEntry:
    entity_type: BestsellerEntityType
    external_id: str
    rank: int
    display_name: str | None
    gmv: DesensitizedGmvRange
    extensions: dict[str, Any]
    raw_payload: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class TikTokBestsellerPage:
    entries: list[TikTokBestsellerEntry]
    platform_request_id: str | None


@dataclass(frozen=True)
class TikTokBestsellerResponseSpec:
    entity_type: BestsellerEntityType
    node: str
    id_field: str
    display_fields: tuple[str, ...]


RESPONSE_SPECS: dict[BestsellerEntityType, TikTokBestsellerResponseSpec] = {
    "product": TikTokBestsellerResponseSpec("product", "products", "id", ("name",)),
    "creator": TikTokBestsellerResponseSpec(
        "creator", "creators", "open_id", ("nick_name", "user_name")
    ),
    "video": TikTokBestsellerResponseSpec("video", "videos", "id", ("nick_name",)),
    "live": TikTokBestsellerResponseSpec("live", "lives", "id", ("title",)),
}


def parse_bestseller_page(
    payload: dict[str, Any],
    *,
    entity_type: BestsellerEntityType,
    currency: BestsellerCurrency,
    platform_request_id: str | None,
) -> TikTokBestsellerPage:
    spec = RESPONSE_SPECS[entity_type]
    data = payload.get("data")
    if not isinstance(data, dict):
        raise _invalid(platform_request_id)
    items = data.get(spec.node)
    if not isinstance(items, list):
        raise _invalid(platform_request_id)

    entries: list[TikTokBestsellerEntry] = []
    for item in items:
        if not isinstance(item, dict):
            raise _invalid(platform_request_id)
        entries.append(
            _parse_entry(
                item,
                spec=spec,
                currency=currency,
                platform_request_id=platform_request_id,
            )
        )
    return TikTokBestsellerPage(
        entries=entries,
        platform_request_id=platform_request_id,
    )


def _parse_entry(
    item: dict[str, Any],
    *,
    spec: TikTokBestsellerResponseSpec,
    currency: BestsellerCurrency,
    platform_request_id: str | None,
) -> TikTokBestsellerEntry:
    external_id = item.get(spec.id_field)
    rank = item.get("rank")
    gmv_range = item.get("gmv_range")
    if (
        not isinstance(external_id, str)
        or not external_id
        or not isinstance(rank, int)
        or isinstance(rank, bool)
        or rank < 1
        or not isinstance(gmv_range, str)
        or not gmv_range
    ):
        raise _invalid(platform_request_id)

    display_field, display_name = _display_value(item, spec.display_fields)
    common_fields = {spec.id_field, "rank", "gmv_range"}
    if display_field:
        common_fields.add(display_field)
    extensions = {
        key: deepcopy(value) for key, value in item.items() if key not in common_fields
    }
    return TikTokBestsellerEntry(
        entity_type=spec.entity_type,
        external_id=external_id,
        rank=rank,
        display_name=display_name,
        gmv=DesensitizedGmvRange(raw=gmv_range, currency_context=currency),
        extensions=extensions,
        raw_payload=deepcopy(item),
    )


def _display_value(
    item: dict[str, Any], candidates: tuple[str, ...]
) -> tuple[str | None, str | None]:
    for field in candidates:
        value = item.get(field)
        if isinstance(value, str) and value:
            return field, value
    return None, None


def _invalid(platform_request_id: str | None) -> TikTokApiError:
    return TikTokApiError(
        "TikTok bestselling response had an invalid shape.",
        code="invalid_bestseller_response",
        status_code=502,
        request_id=platform_request_id,
    )
