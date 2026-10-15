from collections.abc import Collection
from uuid import UUID

from sqlalchemy import desc, func, select

from erp_api.models.analytics_snapshot import TikTokVideoContent


def video_avatars_for_usernames(
    tenant_id: UUID,
    shop_id: UUID,
    usernames: Collection[str],
):
    username = TikTokVideoContent.fields["creatorUsername"].astext
    normalized_username = func.lower(func.ltrim(username, "@"))
    avatar_url = TikTokVideoContent.fields["creatorAvatarUrl"].astext
    return (
        select(
            normalized_username.label("username_normalized"),
            avatar_url.label("avatar_url"),
        )
        .distinct(normalized_username)
        .where(
            TikTokVideoContent.tenant_id == tenant_id,
            TikTokVideoContent.shop_id == shop_id,
            username.is_not(None),
            avatar_url.is_not(None),
            avatar_url != "",
            normalized_username.in_(sorted(usernames)),
        )
        .order_by(normalized_username, desc(TikTokVideoContent.observed_at))
    )
