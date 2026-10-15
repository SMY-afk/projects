from collections.abc import Mapping


def creator_report_summary(
    snapshot: Mapping[str, object],
) -> dict[str, int | None]:
    expected = snapshot.get("expected_total")
    return {
        "expected_total": expected if isinstance(expected, int) else None,
        "pages_fetched": capture_count(snapshot.get("pages_fetched")),
        "records_received": capture_count(snapshot.get("records_received")),
        "records_unique": capture_count(snapshot.get("records_unique")),
        "duplicate_count": capture_count(snapshot.get("duplicates")),
    }


def capture_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def creator_partial_reason(value: object):
    if value in {"total_count_mismatch", "cursor_interrupted"}:
        return value
    return "page_failed"
