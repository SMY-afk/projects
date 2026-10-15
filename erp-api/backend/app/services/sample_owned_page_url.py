"""Build an owned sample page URL from a verified authenticated tab."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urlsplit


def build_owned_sample_url(
    targets: list[Mapping[str, object]],
    platform_shop_id: str,
    *,
    host: str,
    path: str,
    approved_target_id: str | None = None,
) -> str | None:
    target = find_owned_sample_target(
        targets, platform_shop_id, host=host, path=path
    )
    if target is not None:
        return target[0]
    if approved_target_id is None:
        return None
    for item in targets:
        if item.get("id") != approved_target_id or item.get("type") != "page":
            continue
        split = urlsplit(str(item.get("url", "")))
        query = parse_qs(split.query)
        if (split.scheme == "https" and split.hostname == host
                and split.path.startswith(("/affiliate/", "/data/", "/insights/"))
                and query.get("shop_id") == [platform_shop_id]
                and len(query.get("shop_region", [])) == 1):
            params = {"shop_region": query["shop_region"][0], "shop_id": platform_shop_id}
            return f"https://{host}{path}?{urlencode(params)}"
    return None


def find_owned_sample_target(
    targets: list[Mapping[str, object]],
    platform_shop_id: str,
    *,
    host: str,
    path: str,
) -> tuple[str, str] | None:
    for target in targets:
        value = target.get("url")
        target_id = target.get("id")
        if (
            target.get("type") != "page"
            or not isinstance(value, str)
            or not isinstance(target_id, str)
        ):
            continue
        split = urlsplit(value)
        query = parse_qs(split.query)
        if (
            split.hostname == host
            and split.path == path
            and query.get("shop_id") == [platform_shop_id]
            and len(query.get("shop_region", [])) == 1
        ):
            params = {"shop_region": query["shop_region"][0], "shop_id": platform_shop_id}
            return f"https://{host}{path}?{urlencode(params)}", target_id
    return None
