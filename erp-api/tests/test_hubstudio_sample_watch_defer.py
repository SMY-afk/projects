import asyncio

from backend.app.services.deferred_sample_post_source import DeferredPostSourceService


def test_deferred_pipeline_skips_profile_and_feishu() -> None:
    called = False

    async def capture_profiles() -> None:
        nonlocal called
        called = True

    result = asyncio.run(
        DeferredPostSourceService().complete_after_source(
            profile_capture=capture_profiles,
        )
    )

    assert result.feishu_result is None
    assert called is False
