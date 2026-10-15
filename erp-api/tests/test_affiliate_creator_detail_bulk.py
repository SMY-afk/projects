from erp_api.services.affiliate_creator_detail_repository import (
    DETAIL_UPSERT_BATCH_SIZE,
    _batches,
)


def test_creator_detail_rows_are_buffered_in_bounded_bulk_batches() -> None:
    rows = [{"value": index} for index in range(701)]

    batches = list(_batches(rows))

    assert DETAIL_UPSERT_BATCH_SIZE == 300
    assert [len(batch) for batch in batches] == [300, 300, 101]
