from types import SimpleNamespace


class DeferredPostSourceService:
    """Allow source ingestion while suppressing all downstream Feishu work."""

    async def complete_after_source(self, **_kwargs):
        return SimpleNamespace(feishu_result=None)
