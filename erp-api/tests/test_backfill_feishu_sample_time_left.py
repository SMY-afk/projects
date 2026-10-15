from scripts.backfill_feishu_sample_time_left import _field_matches


def test_time_left_readback_accepts_feishu_rich_text_segments() -> None:
    assert _field_matches(
        [{"type": "text", "text": "剩余 22 小时 36 分"}],
        "剩余 22 小时 36 分",
    )


def test_time_left_readback_rejects_different_text() -> None:
    assert not _field_matches(
        [{"type": "text", "text": "剩余 2 天"}],
        "剩余 3 天",
    )
