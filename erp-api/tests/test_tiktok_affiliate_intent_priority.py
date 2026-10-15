import asyncio
from uuid import UUID

from backend.app.services.tiktok_affiliate_intent_priority import wait_for_intent


class ImmediateIntentRepository:
    def __init__(self, intent: object) -> None:
        self.intent = intent
        self.platform_shop_ids: frozenset[str] | None = None

    async def next_queued(
        self, tenant_id: UUID, platform_shop_ids: frozenset[str]
    ) -> object:
        self.platform_shop_ids = platform_shop_ids
        return self.intent


def test_foreground_intent_preempts_creator_detail_backfill() -> None:
    async def run() -> tuple[bool, bool, bool, bool]:
        tenant_id = UUID(int=1)
        intent = object()
        stopped = asyncio.Event()
        background_stopped = asyncio.Event()

        async def creator_detail_backfill() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                background_stopped.set()

        background_task = asyncio.create_task(creator_detail_backfill())
        await asyncio.sleep(0)
        repository = ImmediateIntentRepository(intent)
        selected = await wait_for_intent(
            repository,
            tenant_id,
            stopped,
            platform_shop_ids=frozenset({"9622543325839925006"}),
            preempt_tasks=(background_task,),
        )
        return (
            selected is intent,
            background_stopped.is_set(),
            background_task.cancelled(),
            repository.platform_shop_ids == frozenset({"9622543325839925006"}),
        )

    assert asyncio.run(run()) == (True, True, True, True)
