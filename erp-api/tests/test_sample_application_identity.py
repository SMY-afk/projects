from erp_api.services.sample_application_identity import display_application_id


def test_single_application_displays_its_real_tiktok_id() -> None:
    assert display_application_id(
        "creator-group:internal-key",
        raw_payload={"source_item_ids": ["9415449469306011580"]},
    ) == "9415449469306011580"


def test_multiple_products_stay_in_one_cell_with_real_tiktok_ids() -> None:
    assert display_application_id(
        "creator-group:internal-key",
        raw_payload={
            "source_item_ids": [
                "9415449469306011580",
                "9054717548688115617",
                "9415449469306011580",
            ]
        },
    ) == "9415449469306011580、9054717548688115617"


def test_group_key_is_never_exposed_when_source_id_is_missing() -> None:
    assert display_application_id("creator-group:internal-key") == ""
