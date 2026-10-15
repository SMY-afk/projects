from sqlalchemy import and_, case, func

CACHED_AVATAR_PREFIX = "https://example.invalid/configure-resource"


def retained_avatar(current: str | None, incoming: str | None) -> str | None:
    if current and current.startswith(CACHED_AVATAR_PREFIX) and not (incoming or "").startswith(CACHED_AVATAR_PREFIX):
        return current
    return incoming or current


def cached_avatar_expression(current, incoming):
    return case((and_(current.like(CACHED_AVATAR_PREFIX + "%"),
                      ~func.coalesce(incoming, "").like(CACHED_AVATAR_PREFIX + "%")), current),
                else_=func.coalesce(incoming, current))
