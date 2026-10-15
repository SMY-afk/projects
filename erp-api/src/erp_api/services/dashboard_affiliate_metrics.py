from __future__ import annotations

from erp_api.services.sample_bd_assignment import CREATOR_LEVELS


def level_items(counts: dict[str, int]) -> list[dict[str, object]]:
    known = sum(counts.values())
    return [
        {
            "level": level,
            "count": counts.get(level, 0),
            "share": round(counts.get(level, 0) / known * 100, 1) if known else 0,
        }
        for level in reversed(CREATOR_LEVELS)
    ]


def identity_keys(open_id: object, username: object) -> tuple[str, ...]:
    keys = []
    if isinstance(open_id, str) and open_id.strip():
        keys.append(f"id:{open_id.strip()}")
    if isinstance(username, str) and username.strip():
        keys.append(f"user:{username.strip().lstrip('@').casefold()}")
    return tuple(keys)


def efficiency_payload(pages, statuses, period, *, expected_shop_count):
    rows = []
    for shop, page in pages:
        for item in page.get("items", []):
            gmv = max(0, int(item.get("affiliateGmvMinor") or 0))
            videos = max(0, int(item.get("affiliateVideoCount") or 0))
            keys = identity_keys(item.get("creatorOpenId"), item.get("username"))
            sample_status = next(
                (
                    statuses[(shop["id"], key)]
                    for key in keys
                    if (shop["id"], key) in statuses
                ),
                None,
            )
            rows.append(
                {
                    "id": f"{shop['id']}:{item['id']}",
                    "username": str(item.get("username") or "未命名达人"),
                    "avatarUrl": item.get("avatarUrl"),
                    "shopName": shop["name"],
                    "videoCount": videos,
                    "gmvMinor": gmv,
                    "gmvPerVideoMinor": round(gmv / videos) if videos else 0,
                    "sampleStatus": sample_status,
                }
            )
    rows.sort(key=lambda item: (-item["gmvMinor"], item["username"].casefold()))
    total_gmv = sum(item["gmvMinor"] for item in rows)
    cumulative = 0
    for rank, row in enumerate(rows, 1):
        cumulative += row["gmvMinor"]
        row["rank"] = rank
        row["cumulativeGmvShare"] = (
            round(cumulative / total_gmv * 100, 2) if total_gmv else 0
        )
    start, end = period
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "complete": len(pages) == expected_shop_count,
        "shopCount": len(pages),
        "totalCreators": len(rows),
        "totalGmvMinor": total_gmv,
        "rows": rows[:100],
        "pareto": [
            {
                "id": row["id"],
                "username": row["username"],
                "shopName": row["shopName"],
                "gmvMinor": row["gmvMinor"],
                "cumulativeGmvShare": row["cumulativeGmvShare"],
            }
            for row in rows[:20]
        ],
    }


def empty_efficiency() -> dict[str, object]:
    return {
        "period": None,
        "complete": False,
        "shopCount": 0,
        "totalCreators": 0,
        "totalGmvMinor": 0,
        "rows": [],
        "pareto": [],
    }
