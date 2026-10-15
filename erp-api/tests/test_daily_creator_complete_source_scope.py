import pytest

from scripts.daily_valid_creator_pipeline import validate_sources


def test_filtered_view_cannot_publish_even_a_zero_difference_daily_sync():
    source = {"source": "feishu-bitable-readonly", "accounts": {
        "scope": "filtered_view", "total": 1, "rows": []}}
    with pytest.raises(ValueError, match="physical table"):
        validate_sources(source, {}, {}, {})
