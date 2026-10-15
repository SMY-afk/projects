from erp_api.services.analytics_content_upsert import (
    CONTENT_UPSERT_BATCH_SIZE,
    content_batches,
)
from erp_api.services.video_performance_repository import (
    PERFORMANCE_UPSERT_BATCH_SIZE,
    _batches,
)


def test_video_content_and_performance_buffers_are_bounded_to_300_rows() -> None:
    rows = [{"value": index} for index in range(701)]

    assert CONTENT_UPSERT_BATCH_SIZE == PERFORMANCE_UPSERT_BATCH_SIZE == 300
    assert [len(batch) for batch in content_batches(rows)] == [300, 300, 101]
    assert [len(batch) for batch in _batches(rows)] == [300, 300, 101]
