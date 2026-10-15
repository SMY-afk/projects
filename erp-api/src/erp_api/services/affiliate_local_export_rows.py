from collections.abc import Mapping


def creator_export_row(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "username": item.get("username"),
        "affiliateGmvMinor": item.get("affiliateGmvMinor"),
    }


def video_export_row(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "creatorUsername": item.get("creatorUsername"),
        "creatorNickname": item.get("creatorNickname"),
        "videoPostTime": item.get("videoPostTime"),
    }


def live_export_row(item) -> dict[str, object]:
    fields = item.fields if isinstance(item.fields, Mapping) else {}
    return {
        "fields": {
            "username": fields.get("username"),
            "startTime": fields.get("startTime"),
        },
        "observedAt": item.observed_at,
    }
