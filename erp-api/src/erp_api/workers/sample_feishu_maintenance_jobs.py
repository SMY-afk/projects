from __future__ import annotations

from uuid import uuid4

BD_INVITATION_REFRESH_LOCK = "sample:bd_invitation:refresh_lock"
_UNLOCK_IF_OWNED = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


async def cleanup_bd_invitation_protection_job(ctx) -> int:
    service = ctx.get("sample_bd_invitation_protection_service")
    if service is None:
        return 0
    redis = ctx.get("redis")
    if redis is None:
        return (await service.refresh(save_ai_snapshot=True)).deleted_count
    owner = uuid4().hex
    if not await redis.set(BD_INVITATION_REFRESH_LOCK, owner, nx=True, ex=600):
        return 0
    try:
        return (await service.refresh(save_ai_snapshot=True)).deleted_count
    finally:
        await redis.eval(_UNLOCK_IF_OWNED, 1, BD_INVITATION_REFRESH_LOCK, owner)


async def sync_ai_invitation_mirror_job(ctx) -> dict[str, int]:
    service = ctx.get("sample_ai_invitation_mirror_service")
    if service is None:
        return {
            "source_count": 0,
            "target_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "deleted_count": 0,
        }
    result = await service.sync()
    return {
        "source_count": result.source_count,
        "target_count": result.target_count,
        "created_count": result.created_count,
        "updated_count": result.updated_count,
        "deleted_count": result.deleted_count,
    }
