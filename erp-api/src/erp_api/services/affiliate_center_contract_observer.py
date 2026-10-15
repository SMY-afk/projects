from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from erp_api.services.affiliate_center_payload_contract import (
    AffiliatePayloadDiscriminatorError,
    classify_pagination_mode,
    require_affiliate_payload,
)

_REQUEST_ID_HEADER_KEYS = frozenset(
    {
        "request-id",
        "x-request-id",
        "x-tt-logid",
        "x-tt-trace-id",
    }
)
_REQUEST_ID_PAYLOAD_KEYS = frozenset({"logid", "requestid", "traceid"})
_PAGINATION_KEYS = frozenset(
    {
        "cursor",
        "hasmore",
        "limit",
        "nextcursor",
        "nextpage",
        "offset",
        "page",
        "pageindex",
        "pagenum",
        "pagesize",
        "total",
        "totalcount",
        "totalpage",
    }
)
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_MAX_FIELD_PATHS = 5_000
_MAX_DEPTH = 16


class ContractObservationError(ValueError):
    pass


def observe_response_contract(
    *,
    resource: str | None = None,
    url: str,
    method: str,
    status: int,
    response_headers: Mapping[str, str],
    payload: object,
) -> dict[str, object]:
    """Return structural response metadata without request or business values."""
    parsed_url = urlsplit(url)
    if not parsed_url.hostname or not parsed_url.path:
        raise ContractObservationError("Response URL must include host and path.")
    if isinstance(status, bool) or not isinstance(status, int):
        raise ContractObservationError("Response status must be an integer.")

    safe_headers = {key.casefold(): value for key, value in response_headers.items()}
    field_paths: set[str] = set()
    pagination_fields: set[str] = set()
    request_ids: list[dict[str, str]] = []

    discriminator: str | None = None
    if resource is not None:
        try:
            discriminator = require_affiliate_payload(resource, payload)
        except AffiliatePayloadDiscriminatorError as exc:
            raise ContractObservationError(
                "Payload discriminator rejected the response."
            ) from exc

    _collect_payload_contract(
        payload,
        path="",
        depth=0,
        field_paths=field_paths,
        pagination_fields=pagination_fields,
        request_ids=request_ids,
    )
    for key in sorted(_REQUEST_ID_HEADER_KEYS):
        value = safe_headers.get(key)
        if value is not None and _SAFE_REQUEST_ID.fullmatch(value):
            request_ids.append({"source": f"header.{key}", "value": value})

    request_ids.sort(key=lambda item: item["source"])
    observation: dict[str, object] = {
        "host": parsed_url.hostname,
        "method": method.upper(),
        "path": parsed_url.path,
        "contentType": safe_headers.get("content-type"),
        "status": status,
        "paginationFields": sorted(pagination_fields),
        "responseFieldPaths": sorted(field_paths),
        "requestIds": request_ids,
    }
    if discriminator is not None:
        observation["payloadDiscriminator"] = discriminator
        observation["pagination"] = classify_pagination_mode(field_paths)
    return observation


def _collect_payload_contract(
    value: object,
    *,
    path: str,
    depth: int,
    field_paths: set[str],
    pagination_fields: set[str],
    request_ids: list[dict[str, str]],
) -> None:
    if depth > _MAX_DEPTH:
        raise ContractObservationError("Response payload exceeds maximum depth.")
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise ContractObservationError(
                    "Response payload keys must be non-empty strings."
                )
            item_path = f"{path}.{raw_key}" if path else raw_key
            _add_field_path(field_paths, item_path)
            normalized_key = re.sub(r"[^a-z0-9]", "", raw_key.casefold())
            if normalized_key in _PAGINATION_KEYS:
                pagination_fields.add(item_path)
            if (
                normalized_key in _REQUEST_ID_PAYLOAD_KEYS
                and isinstance(item, str)
                and _SAFE_REQUEST_ID.fullmatch(item)
            ):
                request_ids.append({"source": f"payload.{item_path}", "value": item})
            _collect_payload_contract(
                item,
                path=item_path,
                depth=depth + 1,
                field_paths=field_paths,
                pagination_fields=pagination_fields,
                request_ids=request_ids,
            )
        return
    if isinstance(value, (list, tuple)):
        list_path = f"{path}[]"
        _add_field_path(field_paths, list_path)
        for item in value:
            _collect_payload_contract(
                item,
                path=list_path,
                depth=depth + 1,
                field_paths=field_paths,
                pagination_fields=pagination_fields,
                request_ids=request_ids,
            )


def _add_field_path(field_paths: set[str], path: str) -> None:
    field_paths.add(path)
    if len(field_paths) > _MAX_FIELD_PATHS:
        raise ContractObservationError("Response payload has too many field paths.")
