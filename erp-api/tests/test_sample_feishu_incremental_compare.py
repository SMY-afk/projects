from erp_api.services.sample_feishu_sync_support import _field_values_match


def test_numeric_feishu_strings_match_postgres_numbers() -> None:
    assert _field_values_match(359, "359")
    assert _field_values_match(82.28, "82.28")
    assert _field_values_match(0.8228, "0.8228")


def test_different_numeric_values_do_not_match() -> None:
    assert not _field_values_match(359, "358")
    assert not _field_values_match(82.28, "82.29")
