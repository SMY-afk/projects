from collections.abc import Mapping

CONTENT_FIELD_NAMES = frozenset(
    {
        "title",
        "username",
        "creatorOpenId",
        "creatorUsername",
        "creatorNickname",
        "creatorAuthorType",
        "videoPostTime",
        "durationSeconds",
        "hashTags",
        "promotedProducts",
        "coverImageUrl",
    }
)

ACCOUNT_TYPES = frozenset(
    {
        "ALL",
        "OFFICIAL_ACCOUNTS",
        "MARKETING_ACCOUNTS",
        "AFFILIATE_ACCOUNTS",
    }
)


def merge_windowed_fields(
    content_fields: Mapping[str, object], metrics: Mapping[str, object]
) -> dict[str, object]:
    metadata = {
        key: value
        for key, value in content_fields.items()
        if key in CONTENT_FIELD_NAMES
    }
    return {**metadata, **metrics}
