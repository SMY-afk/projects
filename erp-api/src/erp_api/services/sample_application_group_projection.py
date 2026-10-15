from __future__ import annotations

from collections.abc import Mapping, Sequence


def application_group_projections(
    applications: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    projections = []
    for application in applications:
        parent_id = application.get("id")
        source_ids = application.get("source_item_ids")
        products = application.get("products")
        status = application.get("status")
        if (
            not isinstance(parent_id, str)
            or not isinstance(status, str)
            or not isinstance(source_ids, list)
            or not isinstance(products, list)
        ):
            continue
        normalized_ids = list(
            dict.fromkeys(
                value.strip()
                for value in source_ids
                if isinstance(value, str) and value.strip()
            )
        )
        if parent_id not in normalized_ids or len(normalized_ids) != len(source_ids):
            continue
        product_values: dict[str, list[str]] = {
            "id": [],
            "title": [],
            "sku_id": [],
            "sku_name": [],
            "sku_image_url": [],
        }
        for item in products:
            product = item.get("product") if isinstance(item, Mapping) else None
            if not isinstance(product, Mapping):
                continue
            for key, values in product_values.items():
                value = product.get(key)
                if isinstance(value, str) and value.strip() and value.strip() not in values:
                    values.append(value.strip())
        projections.append(
            {
                "parent_application_id": parent_id,
                "source_item_ids": normalized_ids,
                "platform_status": status,
                "product_id": _joined(product_values["id"]),
                "product_title": _joined(product_values["title"]),
                "sku_id": _joined(product_values["sku_id"]),
                "sku_name": _joined(product_values["sku_name"]),
                "product_image_urls": product_values["sku_image_url"],
                "product_ids": product_values["id"],
            }
        )
    return tuple(projections)


def obsolete_group_application_ids(
    applications: Sequence[Mapping[str, object]],
) -> frozenset[str]:
    return frozenset(
        source_id
        for projection in application_group_projections(applications)
        for source_id in projection["source_item_ids"]
        if source_id != projection["parent_application_id"]
    )


def expand_application_group_projection(
    projection: dict[str, object], members: Sequence[object]
) -> dict[str, object]:
    expanded = dict(projection)
    source_ids = _unique(
        [*projection["source_item_ids"], *(member.platform_application_id for member in members)]
    )
    field_names = ("product_id", "product_title", "sku_id", "sku_name")
    for field_name in field_names:
        existing = projection.get(field_name)
        values = existing.split("、") if isinstance(existing, str) else []
        values.extend(
            part
            for member in members
            if isinstance((value := getattr(member, field_name, None)), str)
            for part in value.split("、")
        )
        expanded[field_name] = _joined(_unique(values))
    images = list(projection.get("product_image_urls") or [])
    images.extend(
        image
        for member in members
        for image in (getattr(member, "product_image_urls", None) or [])
        if isinstance(image, str)
    )
    expanded["source_item_ids"] = source_ids
    expanded["product_image_urls"] = _unique(images)
    expanded["product_ids"] = (
        expanded["product_id"].split("、") if expanded["product_id"] else []
    )
    return expanded


def stabilize_application_group_projection(
    projection: dict[str, object], raw_payload: object
) -> dict[str, object]:
    """Keep verified details when a UI refresh has the same group identity."""
    if not isinstance(raw_payload, Mapping):
        return projection
    previous = raw_payload.get("ziniao_group_projection")
    if not isinstance(previous, Mapping):
        return projection
    for key in ("parent_application_id", "platform_status"):
        if previous.get(key) != projection.get(key):
            return projection
    for key in ("source_item_ids", "product_ids"):
        old_ids = previous.get(key)
        new_ids = projection.get(key)
        if not isinstance(old_ids, list) or not isinstance(new_ids, list):
            return projection
        if set(old_ids) != set(new_ids):
            return projection
    return dict(previous)


def _joined(values: list[str]) -> str | None:
    return "、".join(values) or None


def _unique(values) -> list[str]:
    return list(
        dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip())
    )
